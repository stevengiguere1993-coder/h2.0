"""Import one-shot des données Monday → h2.0.

À exécuter UNE FOIS via Render Shell après avoir mis MONDAY_TOKEN dans
les env vars du service backend :

    cd /opt/render/project/src/backend
    python -m scripts.import_monday

Idempotent : ré-exécutable sans créer de doublons (dédup par nom).

Mappings :
- CRM Soumissions board (15 items) → ContactRequest + Soumission
  Si statut « Convertie en projet » → ajoute Client + Project liés.
- Calendrier de construction (6 items) → Project standalone

Après l'import : supprime le fichier, retire MONDAY_TOKEN des env vars,
révoque le token côté Monday.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Permet de lancer ce module en standalone : ajoute le répertoire
# parent (backend/) au sys.path pour résoudre `app.*`.
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
# Constantes Monday
# ---------------------------------------------------------------------------

MONDAY_API_URL = "https://api.monday.com/v2"
BOARD_CRM_SOUMISSIONS = 18400565505
BOARD_CALENDRIER = 18399084844

# Mapping statut Monday → statut h2.0 ContactRequest
CRM_STATUS_MAP = {
    "Convertie en projet": ContactRequestStatus.WON,
    "En attente de décision": ContactRequestStatus.QUOTED,
    "En préparation": ContactRequestStatus.QUALIFIED,
    "Relance 1": ContactRequestStatus.QUOTED,
    "Relance 2": ContactRequestStatus.QUOTED,
    "Perdue": ContactRequestStatus.LOST,
    "Refusée": ContactRequestStatus.LOST,
}

# Mapping vers SoumissionStatus
SOUMISSION_STATUS_MAP = {
    "Convertie en projet": SoumissionStatus.ACCEPTED,
    "En attente de décision": SoumissionStatus.SENT,
    "En préparation": SoumissionStatus.DRAFT,
    "Relance 1": SoumissionStatus.SENT,
    "Relance 2": SoumissionStatus.SENT,
    "Perdue": SoumissionStatus.REJECTED,
    "Refusée": SoumissionStatus.REJECTED,
}

# Mapping type projet
TYPE_PROJET_MAP = {
    "Residentiel": ProjectType.RENOVATION_COMPLETE,
    "multi-logements": ProjectType.MULTILOGEMENT,
    "Salle de bain": ProjectType.SALLE_BAIN,
    "Cuisine": ProjectType.CUISINE,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def monday_query(query: str, token: str) -> Dict[str, Any]:
    """Appel HTTP à l'API Monday."""
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
            raise RuntimeError(f"Monday API error: {data['errors']}")
        return data["data"]


def get_col(item: Dict[str, Any], col_id: str) -> Optional[str]:
    """Lit la valeur texte d'une colonne d'un item Monday."""
    for cv in item.get("column_values", []):
        if cv.get("id") == col_id:
            return cv.get("text") or None
    return None


def parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def derive_email(name: str, item_id: str) -> str:
    """Email placeholder pour l'import (ContactRequest.email est NOT NULL)."""
    safe = (
        "".join(c.lower() if c.isalnum() else "" for c in (name or "").strip())
        or f"item{item_id}"
    )[:40]
    return f"import+{safe}.{item_id}@horizon.local"


def derive_project_type(monday_type: Optional[str], item_name: str) -> str:
    if monday_type and monday_type in TYPE_PROJET_MAP:
        return TYPE_PROJET_MAP[monday_type].value
    n = (item_name or "").lower()
    if "salle de bain" in n or "sdb" in n:
        return ProjectType.SALLE_BAIN.value
    if "cuisine" in n:
        return ProjectType.CUISINE.value
    if "logement" in n or "appart" in n or "multi" in n:
        return ProjectType.MULTILOGEMENT.value
    return ProjectType.AUTRE.value


# ---------------------------------------------------------------------------
# Import logic
# ---------------------------------------------------------------------------


async def fetch_items(board_id: int, token: str) -> List[Dict[str, Any]]:
    query = (
        f"query {{ boards(ids: [{board_id}]) {{ items_page(limit: 100) "
        "{ items { id name group { id title } "
        "column_values { id text value } } } } }"
    )
    data = await monday_query(query, token)
    return data["boards"][0]["items_page"]["items"]


async def import_crm_soumissions(
    db: AsyncSession, items: List[Dict[str, Any]]
) -> Dict[str, int]:
    """Import des items CRM Soumissions → ContactRequest + Soumission
    (+ Client + Project si converti)."""
    counts = {
        "contacts_created": 0,
        "contacts_skipped": 0,
        "soumissions_created": 0,
        "soumissions_skipped": 0,
        "clients_created": 0,
        "projects_created": 0,
    }

    for it in items:
        title = it["name"]
        item_id = it["id"]
        client_name = get_col(it, "text_mm0ykm8z") or "(client à déterminer)"
        date_demande = get_col(it, "date_mm0pb57")
        statut_mdy = get_col(it, "color_mm0ps54") or "En préparation"
        responsable = get_col(it, "multiple_person_mm0pqg8r")
        location = get_col(it, "location_mm0xs8d3")
        type_projet_mdy = get_col(it, "dropdown_mm0p14e")
        budget_str = get_col(it, "numeric_mm0p2z9b")
        notes_visite = get_col(it, "long_text_mm0p4j8b")
        commentaire = get_col(it, "long_text_mm24zgv")
        date_envoi = get_col(it, "date_mm0xdp6f")

        budget = None
        if budget_str:
            try:
                budget = float(budget_str)
            except (ValueError, TypeError):
                pass

        # Email placeholder (ContactRequest.email est NOT NULL)
        email = derive_email(client_name, item_id)

        # Dédup ContactRequest par email
        existing_cr = (
            await db.execute(
                select(ContactRequest).where(ContactRequest.email == email)
            )
        ).scalar_one_or_none()

        if existing_cr:
            cr = existing_cr
            counts["contacts_skipped"] += 1
        else:
            # Notes internes : on garde tout ce que Monday avait
            internal_notes_parts = [
                f"Importé depuis Monday CRM Soumissions (item {item_id})",
                f"Statut Monday: {statut_mdy}",
            ]
            if responsable:
                internal_notes_parts.append(f"Responsable: {responsable}")
            if notes_visite:
                internal_notes_parts.append(f"Notes visite: {notes_visite}")
            if commentaire:
                internal_notes_parts.append(f"Commentaire client: {commentaire}")

            cr = ContactRequest(
                name=client_name,
                email=email,
                phone=None,
                address=location,
                project_type=derive_project_type(type_projet_mdy, title),
                message=title or "(import Monday — pas de message)",
                status=CRM_STATUS_MAP.get(
                    statut_mdy, ContactRequestStatus.NEW
                ).value,
                source="monday-import",
                gdpr_consent=True,
                marketing_consent=False,
                locale="fr",
                internal_notes="\n".join(internal_notes_parts),
            )
            db.add(cr)
            await db.flush()
            counts["contacts_created"] += 1

        # Soumission liée — référence "MDY-{item_id}" pour ne pas
        # consommer le compteur QB, mais quand même unique.
        ref = f"MDY-{item_id}"
        existing_s = (
            await db.execute(
                select(Soumission).where(Soumission.reference == ref)
            )
        ).scalar_one_or_none()

        if existing_s:
            soum = existing_s
            counts["soumissions_skipped"] += 1
        else:
            sent_at = parse_date(date_envoi)
            soum_status = SOUMISSION_STATUS_MAP.get(
                statut_mdy, SoumissionStatus.DRAFT
            ).value
            soum = Soumission(
                reference=ref,
                contact_request_id=cr.id,
                title=title,
                description=notes_visite or None,
                subtotal=budget,
                total=budget,  # sans calcul taxes pour l'import
                status=soum_status,
                sent_at=sent_at,
                accepted_at=(
                    datetime.now(timezone.utc)
                    if statut_mdy == "Convertie en projet"
                    else None
                ),
                notes=(
                    f"Importé Monday {item_id}. "
                    f"Adresse: {location or '-'}. "
                    f"Demandée le {date_demande or '?'}."
                ),
            )
            db.add(soum)
            await db.flush()
            counts["soumissions_created"] += 1

        # Si convertie en projet → on crée Client + Project liés
        if statut_mdy == "Convertie en projet":
            # Client : dédup par nom (case insensitive)
            existing_cli = (
                await db.execute(
                    select(Client).where(
                        Client.name.ilike(client_name)
                    )
                )
            ).scalar_one_or_none()
            if existing_cli:
                client = existing_cli
            else:
                client = Client(
                    name=client_name,
                    email=None,
                    phone=None,
                    address=location,
                    notes=f"Importé Monday CRM Soumissions {item_id}",
                    contact_request_id=cr.id,
                )
                db.add(client)
                await db.flush()
                counts["clients_created"] += 1

            # Project : dédup par titre (case insensitive)
            existing_proj = (
                await db.execute(
                    select(Project).where(Project.name.ilike(title))
                )
            ).scalar_one_or_none()
            if not existing_proj:
                proj = Project(
                    name=title,
                    client_id=client.id,
                    contact_request_id=cr.id,
                    soumission_id=soum.id,
                    status=ProjectStatus.IN_PROGRESS.value,
                    address=location,
                    description=notes_visite,
                    budget=budget,
                    notes=f"Importé Monday CRM (item {item_id})",
                )
                db.add(proj)
                await db.flush()
                counts["projects_created"] += 1

    return counts


async def import_calendrier_construction(
    db: AsyncSession, items: List[Dict[str, Any]]
) -> Dict[str, int]:
    """Import des items Calendrier de construction → Project standalone."""
    counts = {"projects_created": 0, "projects_skipped": 0}

    for it in items:
        name = it["name"]
        item_id = it["id"]
        phase = get_col(it, "color_mm0a9h65")  # status
        responsable = get_col(it, "multiple_person_mm0bg9p8")
        date_debut = get_col(it, "date_mm0a3t1d")
        date_fin = get_col(it, "date_mm0asjxa")
        notes_sup = get_col(it, "long_text_mm0aexrc")

        # Dédup par nom
        existing = (
            await db.execute(
                select(Project).where(Project.name.ilike(name))
            )
        ).scalar_one_or_none()
        if existing:
            counts["projects_skipped"] += 1
            continue

        # Map phase → ProjectStatus
        # Monday phases: Démarrage, Démolition, Plomberie, Électricité,
        # Finition, Livré...
        if phase and "livr" in phase.lower():
            status = ProjectStatus.DELIVERED.value
        elif phase and "pause" in phase.lower():
            status = ProjectStatus.SUSPENDED.value
        else:
            # Par défaut : in progress (le calendrier ne contient que
            # des chantiers actifs)
            status = ProjectStatus.IN_PROGRESS.value

        notes_parts = [
            f"Importé Monday Calendrier de construction (item {item_id})"
        ]
        if phase:
            notes_parts.append(f"Phase Monday: {phase}")
        if responsable:
            notes_parts.append(f"Responsable: {responsable}")
        if notes_sup:
            notes_parts.append(f"Notes superviseur: {notes_sup}")

        try:
            sd = (
                datetime.fromisoformat(date_debut).date()
                if date_debut
                else None
            )
        except (ValueError, TypeError):
            sd = None
        try:
            ed = (
                datetime.fromisoformat(date_fin).date()
                if date_fin
                else None
            )
        except (ValueError, TypeError):
            ed = None

        proj = Project(
            name=name,
            status=status,
            start_date=sd,
            end_date=ed,
            description=notes_sup,
            notes="\n".join(notes_parts),
        )
        db.add(proj)
        await db.flush()
        counts["projects_created"] += 1

    return counts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main(dry_run: bool = False) -> None:
    token = os.environ.get("MONDAY_TOKEN")
    if not token:
        print("ERROR: MONDAY_TOKEN n'est pas défini dans l'environnement.")
        print(
            "Ajoute-le temporairement dans Render → backend → Environment, "
            "puis relance."
        )
        sys.exit(1)

    print(
        f"\n{'=' * 60}\nImport Monday → h2.0 "
        f"({'DRY RUN' if dry_run else 'LIVE'})\n{'=' * 60}"
    )

    # 1. Fetch les items Monday
    print("\n→ Fetch CRM Soumissions...")
    crm_items = await fetch_items(BOARD_CRM_SOUMISSIONS, token)
    print(f"  {len(crm_items)} items récupérés")

    print("→ Fetch Calendrier de construction...")
    cal_items = await fetch_items(BOARD_CALENDRIER, token)
    print(f"  {len(cal_items)} items récupérés")

    # 2. Import en DB
    async with AsyncSessionLocal() as db:
        print("\n→ Import CRM Soumissions...")
        crm_counts = await import_crm_soumissions(db, crm_items)
        for k, v in crm_counts.items():
            print(f"  {k}: {v}")

        print("\n→ Import Calendrier de construction...")
        cal_counts = await import_calendrier_construction(db, cal_items)
        for k, v in cal_counts.items():
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
    asyncio.run(main(dry_run=dry))
