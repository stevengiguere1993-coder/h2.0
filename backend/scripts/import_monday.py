"""Import one-shot Monday → h2.0 (v3).

Source de vérité par board :
- Clients (42 items)         → filtrés à ceux liés à au moins une
                                 CRM Soumission. Si lié à un Devis
                                 « accepte » → h2.0 Client, sinon
                                 → h2.0 ContactRequest (prospect).
- Devis clients (9 items)    → h2.0 Soumission avec vrai numéro
                                 (1001..1010), montant, QB Estimate
                                 ID + URL.
- CRM Soumissions (15 items) → importé en h2.0 Soumission DRAFT
                                 SEULEMENT pour les statuts pré-
                                 devis (En préparation, Visite
                                 planifiée/effectuée). Les autres
                                 sont couverts par les Devis.
- Projets (15 items)         → h2.0 Project lié au Client.

Idempotent via --reset (efface tout import Monday précédent).

Usage Render Shell :
    cd /opt/render/project/src/backend
    python -m scripts.import_monday --dry-run --reset
    python -m scripts.import_monday --reset
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import httpx
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.client import Client  # noqa: E402
from app.models.contact_request import (  # noqa: E402
    ContactRequest,
    ContactRequestStatus,
    ProjectType,
)
from app.models.project import Project, ProjectStatus  # noqa: E402
from app.models.soumission import Soumission, SoumissionStatus  # noqa: E402

# ---------------------------------------------------------------------------
# Boards Monday — Horizon Construction
# ---------------------------------------------------------------------------

MONDAY_API_URL = "https://api.monday.com/v2"
BOARD_CLIENTS = 18398667742          # 42 items
BOARD_PROJETS = 18398627396          # 15 items
BOARD_CRM_SOUMISSIONS = 18400565505  # 15 items
BOARD_DEVIS = 18399132469            # 9 items

# ---------------------------------------------------------------------------
# Mappings de statut
# ---------------------------------------------------------------------------

# Statuts Devis
DEVIS_STATUS_MAP = {
    "accepte": SoumissionStatus.ACCEPTED,
    "envoye": SoumissionStatus.SENT,
    "refusé": SoumissionStatus.REJECTED,
    "refuse": SoumissionStatus.REJECTED,
    "expiré": SoumissionStatus.EXPIRED,
    "expire": SoumissionStatus.EXPIRED,
}

# Statuts CRM Soum « pré-devis » : on les importe car ils ne
# correspondent pas encore à un Devis formalisé.
CRM_PRE_DEVIS_STATUSES = {
    "En préparation",
    "En preparation",
    "Visite planifiée",
    "Visite planifiee",
    "Visite effectuée",
    "Visite effectuee",
}

CRM_SOUMISSION_STATUS_MAP = {
    "Convertie en projet": SoumissionStatus.ACCEPTED,
    "Acceptée": SoumissionStatus.ACCEPTED,
    "Acceptee": SoumissionStatus.ACCEPTED,
    "En attente de décision": SoumissionStatus.SENT,
    "Soumission envoyée": SoumissionStatus.SENT,
    "Soumission envoyee": SoumissionStatus.SENT,
    "En préparation": SoumissionStatus.DRAFT,
    "En preparation": SoumissionStatus.DRAFT,
    "Visite effectuée": SoumissionStatus.DRAFT,
    "Visite effectuee": SoumissionStatus.DRAFT,
    "Visite planifiée": SoumissionStatus.DRAFT,
    "Visite planifiee": SoumissionStatus.DRAFT,
    "Relance 1": SoumissionStatus.SENT,
    "Relance 2": SoumissionStatus.SENT,
    "Perdue": SoumissionStatus.REJECTED,
    "Refusée": SoumissionStatus.REJECTED,
}

PROJECT_STATUS_MAP = {
    "Planifié": ProjectStatus.PLANNED,
    "En cours": ProjectStatus.IN_PROGRESS,
    "En pause": ProjectStatus.SUSPENDED,
    "Suspendu": ProjectStatus.SUSPENDED,
    "Livré": ProjectStatus.DELIVERED,
    "Terminé": ProjectStatus.DELIVERED,
}

TYPE_PROJET_MAP = {
    "Residentiel": ProjectType.RENOVATION_COMPLETE,
    "multi-logements": ProjectType.MULTILOGEMENT,
    "Multilogement": ProjectType.MULTILOGEMENT,
    "Salle de bain": ProjectType.SALLE_BAIN,
    "Cuisine": ProjectType.CUISINE,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def monday_query(query: str, token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.post(
            MONDAY_API_URL,
            headers={
                "Authorization": token,
                "Content-Type": "application/json",
            },
            json={"query": query},
        )
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            raise RuntimeError(f"Monday API: {data['errors']}")
        return data["data"]


async def fetch_all_items(board_id: int, token: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        cursor_arg = f', cursor: "{cursor}"' if cursor else ""
        query = (
            f"query {{ boards(ids: [{board_id}]) {{ items_page(limit: 100"
            f"{cursor_arg}) {{ cursor items {{ id name "
            "column_values { id text value } } } } }"
        )
        data = await monday_query(query, token)
        page = data["boards"][0]["items_page"]
        out.extend(page["items"])
        cursor = page.get("cursor")
        if not cursor:
            break
        await asyncio.sleep(0.5)
    return out


def get_col(item: Dict[str, Any], col_id: str) -> Optional[str]:
    for cv in item.get("column_values", []):
        if cv.get("id") == col_id:
            return cv.get("text") or None
    return None


def get_col_value(item: Dict[str, Any], col_id: str) -> Optional[str]:
    for cv in item.get("column_values", []):
        if cv.get("id") == col_id:
            return cv.get("value")
    return None


def parse_relation_ids(item: Dict[str, Any], col_id: str) -> List[str]:
    raw = get_col_value(item, col_id)
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if isinstance(v, dict):
        ids = v.get("linkedPulseIds") or []
        return [
            str(x.get("linkedPulseId"))
            for x in ids
            if x.get("linkedPulseId")
        ]
    return []


def parse_email(item: Dict[str, Any], col_id: str) -> Optional[str]:
    raw = get_col_value(item, col_id)
    if not raw:
        return None
    try:
        v = json.loads(raw)
        e = v.get("email") if isinstance(v, dict) else None
        return e.strip().lower() if e else None
    except (ValueError, TypeError):
        return None


def parse_phone(item: Dict[str, Any], col_id: str) -> Optional[str]:
    raw = get_col_value(item, col_id)
    if not raw:
        return None
    try:
        v = json.loads(raw)
        p = v.get("phone") if isinstance(v, dict) else None
        return p.strip() if p else None
    except (ValueError, TypeError):
        return None


def parse_link(item: Dict[str, Any], col_id: str) -> Optional[str]:
    raw = get_col_value(item, col_id)
    if not raw:
        return None
    try:
        v = json.loads(raw)
        return v.get("url") if isinstance(v, dict) else None
    except (ValueError, TypeError):
        return None


def parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def derive_project_type(monday_type: Optional[str], hint: str) -> str:
    if monday_type and monday_type in TYPE_PROJET_MAP:
        return TYPE_PROJET_MAP[monday_type].value
    n = (hint or "").lower()
    if "salle de bain" in n or "sdb" in n:
        return ProjectType.SALLE_BAIN.value
    if "cuisine" in n:
        return ProjectType.CUISINE.value
    if "logement" in n or "appart" in n or "multi" in n:
        return ProjectType.MULTILOGEMENT.value
    return ProjectType.AUTRE.value


def synthetic_email(monday_id: str) -> str:
    return f"import+monday.{monday_id}@horizon.local"


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


async def reset_imports(db: AsyncSession) -> Dict[str, int]:
    counts = {}
    res = await db.execute(
        delete(Project).where(
            (Project.notes.ilike("%Importé Monday%"))
            | (Project.notes.ilike("%Importe Monday%"))
        )
    )
    counts["projects_deleted"] = res.rowcount or 0
    res = await db.execute(
        delete(Soumission).where(
            (Soumission.reference.like("MDY-%"))
            | (Soumission.notes.ilike("%Importé Monday%"))
            | (Soumission.notes.ilike("%Importe Monday%"))
        )
    )
    counts["soumissions_deleted"] = res.rowcount or 0
    res = await db.execute(
        delete(Client).where(
            (Client.notes.ilike("%Importé Monday%"))
            | (Client.notes.ilike("%Importe Monday%"))
        )
    )
    counts["clients_deleted"] = res.rowcount or 0
    res = await db.execute(
        delete(ContactRequest).where(
            ContactRequest.source == "monday-import"
        )
    )
    counts["contact_requests_deleted"] = res.rowcount or 0
    await db.flush()
    return counts


# ---------------------------------------------------------------------------
# Import logic
# ---------------------------------------------------------------------------


async def import_all(
    db: AsyncSession,
    clients_items: List[Dict[str, Any]],
    soum_items: List[Dict[str, Any]],
    devis_items: List[Dict[str, Any]],
    proj_items: List[Dict[str, Any]],
) -> Dict[str, int]:
    counts = {
        "clients_filtered_out": 0,  # pas de lien CRM Soum
        "clients_created": 0,
        "contact_requests_created": 0,
        "soumissions_devis_created": 0,
        "soumissions_crm_created": 0,
        "soumissions_devis_skipped_no_client": 0,
        "projects_created": 0,
        "projects_skipped_no_client": 0,
    }

    # Index Monday → item
    soum_by_mid = {s["id"]: s for s in soum_items}
    devis_by_mid = {d["id"]: d for d in devis_items}
    proj_by_mid = {p["id"]: p for p in proj_items}

    # ---- Étape 1 : filtrer les Clients à ceux liés à au moins
    # un CRM Soum, et déterminer Client vs ContactRequest selon les
    # statuts des soumissions/devis liés.
    h2_by_monday_client_id: Dict[str, Dict[str, Any]] = {}

    for mc in clients_items:
        mid = mc["id"]
        linked_crm_ids = parse_relation_ids(mc, "board_relation_mm2146bs")
        if not linked_crm_ids:
            counts["clients_filtered_out"] += 1
            continue

        name = mc["name"]
        email = parse_email(mc, "email_mm085sgh")
        phone = parse_phone(mc, "phone_mm084c8b")
        address = get_col(mc, "location_mm0aq054")
        postal = get_col(mc, "text_mm0azq1n")
        type_client = get_col(mc, "color_mm08pyts")
        qb_cust_id = get_col(mc, "text_mm1rqzmx")

        # Décider Client (h2.0) vs ContactRequest (prospect)
        # → Client si une soum CRM est « Convertie en projet » OU si
        #   un Devis est « accepte ».
        is_accepted = False
        for crm_id in linked_crm_ids:
            crm = soum_by_mid.get(crm_id)
            if crm and (get_col(crm, "color_mm0ps54") or "") in {
                "Convertie en projet",
                "Acceptée",
                "Acceptee",
            }:
                is_accepted = True
                break
        if not is_accepted:
            # Aussi vérifier les Devis associés à ce client (board_relation
            # côté client : on n'a pas, mais on peut chercher inverse)
            for dv in devis_items:
                dv_clients = parse_relation_ids(dv, "board_relation_mm0bkm34")
                if mid in dv_clients and (
                    get_col(dv, "color_mm0b7x8g") or ""
                ).lower() == "accepte":
                    is_accepted = True
                    break

        full_address = (address or "").strip()
        if postal and postal not in full_address:
            full_address = f"{full_address}, {postal}".strip(", ")

        notes = (
            f"Importé Monday Clients (item {mid})"
            + (f" · Type: {type_client}" if type_client else "")
            + (f" · Code postal: {postal}" if postal else "")
        )

        if is_accepted:
            client = Client(
                name=name,
                email=email,
                phone=phone,
                address=full_address or None,
                notes=notes,
                qbo_customer_id=qb_cust_id or None,
            )
            db.add(client)
            await db.flush()
            counts["clients_created"] += 1
            h2_by_monday_client_id[mid] = {"kind": "client", "id": client.id}
        else:
            cr = ContactRequest(
                name=name,
                email=email or synthetic_email(mid),
                phone=phone,
                address=full_address or None,
                project_type=ProjectType.AUTRE.value,
                message=f"Prospect importé Monday Clients #{mid}",
                status=ContactRequestStatus.QUOTED.value,
                source="monday-import",
                gdpr_consent=True,
                marketing_consent=False,
                locale="fr",
                internal_notes=notes,
            )
            db.add(cr)
            await db.flush()
            counts["contact_requests_created"] += 1
            h2_by_monday_client_id[mid] = {"kind": "cr", "id": cr.id}

    # ---- Étape 2 : Devis clients → Soumission avec vrai numéro
    for dv in devis_items:
        mid = dv["id"]
        title = dv["name"]
        numero_devis = get_col(dv, "text_mm0br2d6") or f"MDY-{mid}"
        montant = get_col(dv, "numeric_mm0bj4fy")
        try:
            montant_f = float(montant) if montant else None
        except (ValueError, TypeError):
            montant_f = None
        statut_dv = (get_col(dv, "color_mm0b7x8g") or "").lower()
        date_acceptation = get_col(dv, "date_mm0b2ggn")
        date_envoi = get_col(dv, "date_mm24zr8j")
        date_expiration = get_col(dv, "date_mm2411qb")
        qb_estimate_id = get_col(dv, "text_mm1wfx92")
        qb_url = parse_link(dv, "link_mm0bkty2")
        qb_customer_name = get_col(dv, "text_mm24e7jx")

        linked_clients = parse_relation_ids(dv, "board_relation_mm0bkm34")
        h2_client_id = None
        h2_cr_id = None
        if linked_clients:
            target = h2_by_monday_client_id.get(linked_clients[0])
            if target:
                if target["kind"] == "client":
                    h2_client_id = target["id"]
                else:
                    h2_cr_id = target["id"]
        if h2_client_id is None and h2_cr_id is None:
            counts["soumissions_devis_skipped_no_client"] += 1
            continue

        soum = Soumission(
            reference=numero_devis,  # ex. "1005"
            client_id=h2_client_id,
            contact_request_id=h2_cr_id,
            title=title,
            description=None,
            subtotal=montant_f,
            total=montant_f,
            status=DEVIS_STATUS_MAP.get(
                statut_dv, SoumissionStatus.SENT
            ).value,
            sent_at=parse_date(date_envoi),
            accepted_at=parse_date(date_acceptation),
            valid_until=parse_date(date_expiration),
            qbo_estimate_id=qb_estimate_id,
            notes=(
                f"Importé Monday Devis (item {mid}) | Numéro QB: "
                f"{numero_devis}"
                + (f" | URL QB: {qb_url}" if qb_url else "")
                + (f" | Nom QB: {qb_customer_name}" if qb_customer_name else "")
            ),
        )
        db.add(soum)
        await db.flush()
        counts["soumissions_devis_created"] += 1

    # ---- Étape 3 : CRM Soum (pré-devis seulement)
    for crm in soum_items:
        mid = crm["id"]
        title = crm["name"]
        statut = get_col(crm, "color_mm0ps54") or "En préparation"
        if statut not in CRM_PRE_DEVIS_STATUSES:
            # Couvert par les Devis (statuts envoyé/accepté/refusé)
            continue

        budget = get_col(crm, "numeric_mm0p2z9b")
        try:
            budget_f = float(budget) if budget else None
        except (ValueError, TypeError):
            budget_f = None
        notes_visite = get_col(crm, "long_text_mm0p4j8b")
        date_envoi = get_col(crm, "date_mm0xdp6f")
        location = get_col(crm, "location_mm0xs8d3")

        linked_clients = parse_relation_ids(crm, "board_relation_mm21vrg1")
        h2_client_id = None
        h2_cr_id = None
        if linked_clients:
            target = h2_by_monday_client_id.get(linked_clients[0])
            if target:
                if target["kind"] == "client":
                    h2_client_id = target["id"]
                else:
                    h2_cr_id = target["id"]

        if h2_client_id is None and h2_cr_id is None:
            # Pas de client lié → soumission orpheline = prospect
            orphan_cr = ContactRequest(
                name=f"(client à résoudre — {title})",
                email=synthetic_email(f"orphan-{mid}"),
                phone=None,
                address=location,
                project_type=derive_project_type(
                    get_col(crm, "dropdown_mm0p14e"), title
                ),
                message=f"CRM Soum Monday non liée à un client (item {mid})",
                status=ContactRequestStatus.NEW.value,
                source="monday-import",
                gdpr_consent=True,
                marketing_consent=False,
                locale="fr",
                internal_notes=f"Importé Monday CRM Soum {mid}, sans lien client",
            )
            db.add(orphan_cr)
            await db.flush()
            counts["contact_requests_created"] += 1
            h2_cr_id = orphan_cr.id

        soum = Soumission(
            reference=f"MDY-{mid}",
            client_id=h2_client_id,
            contact_request_id=h2_cr_id,
            title=title,
            description=notes_visite,
            subtotal=budget_f,
            total=budget_f,
            status=CRM_SOUMISSION_STATUS_MAP.get(
                statut, SoumissionStatus.DRAFT
            ).value,
            sent_at=parse_date(date_envoi),
            notes=(
                f"Importé Monday CRM Soum {mid} | Statut: {statut}"
                + (f" | Lieu: {location}" if location else "")
            ),
        )
        db.add(soum)
        await db.flush()
        counts["soumissions_crm_created"] += 1

    # ---- Étape 4 : Projets → Project lié au Client
    for mp in proj_items:
        mid = mp["id"]
        name = mp["name"]
        linked_clients = parse_relation_ids(mp, "board_relation_mm08k3pb")
        budget = get_col(mp, "numeric_mm08mhrq")
        try:
            budget_f = float(budget) if budget else None
        except (ValueError, TypeError):
            budget_f = None
        statut_p = get_col(mp, "color_mm0bhkjm")
        date_fin = get_col(mp, "date_mm08c670")
        adresse = (
            get_col(mp, "location_mm0afwxe")
            or get_col(mp, "location_mm0xh10w")
        )

        h2_client_id = None
        if linked_clients:
            target = h2_by_monday_client_id.get(linked_clients[0])
            if target and target["kind"] == "client":
                h2_client_id = target["id"]

        if h2_client_id is None:
            counts["projects_skipped_no_client"] += 1
            # On le crée quand même standalone — sinon on perd le projet
            pass

        try:
            ed = (
                datetime.fromisoformat(date_fin).date()
                if date_fin
                else None
            )
        except (ValueError, TypeError):
            ed = None

        proj_status = (
            PROJECT_STATUS_MAP.get(statut_p, ProjectStatus.IN_PROGRESS).value
            if statut_p
            else ProjectStatus.IN_PROGRESS.value
        )

        proj = Project(
            name=name,
            client_id=h2_client_id,
            status=proj_status,
            address=adresse,
            end_date=ed,
            budget=budget_f,
            notes=(
                f"Importé Monday Projets (item {mid})"
                + (f" | Statut Monday: {statut_p}" if statut_p else "")
            ),
        )
        db.add(proj)
        await db.flush()
        counts["projects_created"] += 1

    return counts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main(dry_run: bool, do_reset: bool) -> None:
    token = os.environ.get("MONDAY_TOKEN")
    if not token:
        print("ERROR: MONDAY_TOKEN n'est pas défini.")
        sys.exit(1)

    print(
        f"\n{'=' * 60}\nImport Monday → h2.0 v3 "
        f"({'DRY RUN' if dry_run else 'LIVE'}"
        f"{', RESET' if do_reset else ''}"
        f")\n{'=' * 60}"
    )

    print("\n→ Fetch Clients (42)...")
    cli = await fetch_all_items(BOARD_CLIENTS, token)
    print(f"  {len(cli)} récupérés")
    print("→ Fetch CRM Soumissions (15)...")
    soum = await fetch_all_items(BOARD_CRM_SOUMISSIONS, token)
    print(f"  {len(soum)} récupérés")
    print("→ Fetch Devis clients (9)...")
    devis = await fetch_all_items(BOARD_DEVIS, token)
    print(f"  {len(devis)} récupérés")
    print("→ Fetch Projets (15)...")
    proj = await fetch_all_items(BOARD_PROJETS, token)
    print(f"  {len(proj)} récupérés")

    async with AsyncSessionLocal() as db:
        if do_reset:
            print("\n→ Cleanup imports Monday précédents...")
            d = await reset_imports(db)
            for k, v in d.items():
                print(f"  {k}: {v}")

        print("\n→ Import...")
        c = await import_all(db, cli, soum, devis, proj)
        for k, v in c.items():
            print(f"  {k}: {v}")

        if dry_run:
            await db.rollback()
            print("\n⚠ DRY RUN — aucun changement persisté.")
        else:
            await db.commit()
            print("\n✓ Commit OK — données persistées.")

    print(f"\n{'=' * 60}\nFini.\n{'=' * 60}\n")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv or os.environ.get("DRY_RUN") == "1"
    rst = "--reset" in sys.argv or os.environ.get("RESET") == "1"
    asyncio.run(main(dry_run=dry, do_reset=rst))
