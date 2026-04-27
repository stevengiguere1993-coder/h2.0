"""Import Monday → Prospection.

Board principal : 7714284220 (« Prospection Immobilière de DEAL »).
Les données sont éclatées sur 3 boards liés :

- 7714284220 : pipeline d'opportunités (item.name = adresse courte,
  étape, score, notes, dates de relance).
- Board lié via `board_relation_mm14vrps` : Propriétaire d'immeuble
  (nom, téléphone, courriel).
- Board lié via `board_relation_mm21e42z` : Info immeuble (adresse
  complète, nb logements, année, valeur).

Le script :
1. Charge tous les items du board principal.
2. Récupère la liste des board_ids référencés (Info immeuble +
   Propriétaire).
3. Charge tous les items de ces boards en bloc.
4. Pour chaque item principal, joint les infos par item_id.
5. Crée/met à jour 1 ProspectionLead par item principal, avec
   monday_item_id pour idempotence.

Usage Render Shell :
    cd ~/project/src/backend
    python -m scripts.import_monday_prospection --inspect
    python -m scripts.import_monday_prospection --dry-run
    python -m scripts.import_monday_prospection
    python -m scripts.import_monday_prospection --reset
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import delete, select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.prospection_lead import (  # noqa: E402
    ProspectionLead,
    ProspectionLeadKind,
    ProspectionLeadStatus,
    ProspectionOwnerKind,
)
from app.services.prospection_scoring import apply_score  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("monday_prosp")


BOARD_ID = 7714284220
MONDAY_API = "https://api.monday.com/v2"


# --------------------------- Column IDs ---------------------------
# IDs identifiés par --inspect du 27 avril 2026. Si Monday change un
# id, mettre à jour ici.

COL_ETAPE = "dup__of__quit___1"        # Statut buy-flow
COL_TYPE = "statut_1__1"                # Type lead (Prospection quartier, …)
COL_QUARTIER = "dropdown_mm14pr0z"      # Quartier (city)
COL_PROPRIO_REL = "board_relation_mm14vrps"  # → Propriétaire
COL_IMMEUBLE_REL = "board_relation_mm21e42z"  # → Info immeuble
COL_SCORE = "numeric_mm131p3j"          # Score opportunité
COL_NB_APPELS = "numeric_mm13x3wr"      # Nombre appels
COL_DATE_LAST_CALL = "date_mm13eyfe"
COL_DATE_LAST_CONTACT = "date_mm13ka1c"
COL_DATE_RELANCE = "date_mm136e44"
COL_NOTES = "long_text_mm13c3x7"
COL_RESULTAT = "color_mm21ag84"
COL_SOURCE = "color_mm21ftyp"


# --------------------------- Status mapping ---------------------------

STATUS_MAP_HINTS: List[Tuple[str, str]] = [
    # Très spécifique d'abord
    ("notaire", ProspectionLeadStatus.CHEZ_NOTAIRE.value),
    ("cession", ProspectionLeadStatus.EN_CESSION.value),
    ("flip", ProspectionLeadStatus.EN_CESSION.value),
    ("nego", ProspectionLeadStatus.EN_NEGO.value),
    ("inspection", ProspectionLeadStatus.EN_INSPECTION.value),
    ("acceptee", ProspectionLeadStatus.OFFRE_ACCEPTEE.value),
    ("offre acceptee", ProspectionLeadStatus.OFFRE_ACCEPTEE.value),
    ("offre acceptée", ProspectionLeadStatus.OFFRE_ACCEPTEE.value),
    ("offre soumise", ProspectionLeadStatus.SOUMISSIONNE.value),
    ("offre", ProspectionLeadStatus.SOUMISSIONNE.value),
    ("promesse", ProspectionLeadStatus.SOUMISSIONNE.value),
    ("achete", ProspectionLeadStatus.CONVERTI.value),
    ("acheté", ProspectionLeadStatus.CONVERTI.value),
    ("cede", ProspectionLeadStatus.CONVERTI.value),
    ("cédé", ProspectionLeadStatus.CONVERTI.value),
    ("perdu", ProspectionLeadStatus.PERDU.value),
    ("refus", ProspectionLeadStatus.PERDU.value),
    ("pas vendable", ProspectionLeadStatus.PERDU.value),
    ("pas interesse", ProspectionLeadStatus.PERDU.value),
    ("pas intéressé", ProspectionLeadStatus.PERDU.value),
    ("abandonne", ProspectionLeadStatus.PERDU.value),
    # « à contacter » avant « contacté » (substring)
    ("a contacter", ProspectionLeadStatus.A_CONTACTER.value),
    ("à contacter", ProspectionLeadStatus.A_CONTACTER.value),
    ("rappeler", ProspectionLeadStatus.A_CONTACTER.value),
    ("a rappeler", ProspectionLeadStatus.A_CONTACTER.value),
    ("contacte", ProspectionLeadStatus.CONTACTE.value),
    ("contacté", ProspectionLeadStatus.CONTACTE.value),
    ("appel fait", ProspectionLeadStatus.CONTACTE.value),
    ("a travailler", ProspectionLeadStatus.A_VISITER.value),
    ("à travailler", ProspectionLeadStatus.A_VISITER.value),
    ("visite", ProspectionLeadStatus.VISITE.value),
    ("repere", ProspectionLeadStatus.A_VISITER.value),
    ("repéré", ProspectionLeadStatus.A_VISITER.value),
    ("nouveau", ProspectionLeadStatus.A_VISITER.value),
]


def _norm(s: str) -> str:
    if not s:
        return ""
    s = "".join(
        c
        for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )
    return s.lower().strip()


def map_status(text: Optional[str]) -> str:
    if not text:
        return ProspectionLeadStatus.A_VISITER.value
    n = _norm(text)
    for hint, status in STATUS_MAP_HINTS:
        if hint in n:
            return status
    return ProspectionLeadStatus.A_VISITER.value


# --------------------------- Monday API ---------------------------


async def monday_query(query: str, token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.post(
            MONDAY_API,
            json={"query": query},
            headers={
                "Authorization": token,
                "Content-Type": "application/json",
                "API-Version": "2024-01",
            },
        )
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            raise RuntimeError(f"Monday API: {data['errors']}")
        return data["data"]


async def fetch_board_meta(board_id: int, token: str) -> Dict[str, Any]:
    query = (
        f"query {{ boards(ids: [{board_id}]) {{ "
        f"id name "
        f"columns {{ id title type }} "
        f"}} }}"
    )
    data = await monday_query(query, token)
    boards = data.get("boards") or []
    if not boards:
        raise RuntimeError(f"Board {board_id} introuvable.")
    return boards[0]


async def fetch_all_items(
    board_id: int, token: str
) -> List[Dict[str, Any]]:
    """Pagine 100 items à la fois."""
    out: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        cursor_arg = f', cursor: "{cursor}"' if cursor else ""
        query = (
            f"query {{ boards(ids: [{board_id}]) {{ items_page(limit: 100"
            f"{cursor_arg}) {{ cursor items {{ id name "
            "column_values { id text value type "
            "... on BoardRelationValue { linked_item_ids } "
            "} } } } }"
        )
        data = await monday_query(query, token)
        page = data["boards"][0]["items_page"]
        out.extend(page["items"])
        cursor = page.get("cursor")
        if not cursor:
            break
        await asyncio.sleep(0.3)
    return out


async def fetch_items_by_ids(
    item_ids: List[str], token: str
) -> Dict[str, Dict[str, Any]]:
    """Charge des items spécifiques (pour suivre les board_relation)."""
    if not item_ids:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    # API Monday : items(ids: [...]) accepte 100 max par requête
    for i in range(0, len(item_ids), 100):
        batch = item_ids[i : i + 100]
        ids_str = ",".join(str(b) for b in batch)
        query = (
            f"query {{ items(ids: [{ids_str}]) {{ id name "
            "column_values { id text value type "
            "... on BoardRelationValue { linked_item_ids } "
            "} } }"
        )
        data = await monday_query(query, token)
        for it in data.get("items", []):
            out[str(it["id"])] = it
        await asyncio.sleep(0.3)
    return out


# --------------------------- Value extraction ---------------------------


def get_text(item: Dict[str, Any], col_id: str) -> Optional[str]:
    for cv in item.get("column_values", []):
        if cv.get("id") == col_id:
            t = cv.get("text")
            return t.strip() if t else None
    return None


def get_linked_ids(item: Dict[str, Any], col_id: str) -> List[str]:
    for cv in item.get("column_values", []):
        if cv.get("id") == col_id:
            ids = cv.get("linked_item_ids")
            if ids:
                return [str(i) for i in ids]
    return []


def parse_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    m = re.search(r"-?\d+", s.replace(" ", "").replace(",", ""))
    return int(m.group()) if m else None


def parse_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", s.replace(",", ".").replace(" ", ""))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    # Monday format: "2026-04-15" ou "2026-04-15 14:30:00"
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def parse_priority_from_score(score: Optional[float]) -> int:
    """Score d'opportunité Monday → priorité 1-5. Heuristique : score
    haut = priorité haute."""
    if score is None:
        return 3
    if score >= 80:
        return 5
    if score >= 60:
        return 4
    if score >= 40:
        return 3
    if score >= 20:
        return 2
    return 1


# --------------------------- Build payload ---------------------------


def extract_address_from_name(name: str) -> Tuple[str, Optional[str]]:
    """L'item name est typiquement « 3976 st-laurent » ou
    « 3976 Saint-Laurent, Montréal ». On retourne (address, city)."""
    if not name:
        return ("", None)
    name = name.strip()
    parts = [p.strip() for p in name.split(",")]
    if len(parts) >= 2:
        return (parts[0], parts[1])
    return (name, None)


def build_lead_payload(
    item: Dict[str, Any],
    proprio: Optional[Dict[str, Any]],
    immeuble: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Construit un dict prêt à insérer dans ProspectionLead."""

    # Adresse + ville : priorité au board Info immeuble si dispo,
    # sinon on parse l'item name du board principal.
    address: Optional[str] = None
    city: Optional[str] = None
    nb_log: Optional[int] = None
    annee: Optional[int] = None
    valeur: Optional[float] = None
    matricule: Optional[str] = None
    postal: Optional[str] = None

    if immeuble is not None:
        # On essaie heuristiquement plusieurs intitulés courants.
        for cv in immeuble.get("column_values", []):
            t = (cv.get("text") or "").strip()
            if not t:
                continue
            cid_t = _norm(cv.get("id", ""))
            # On ne connaît pas les ids du board Info immeuble — on
            # devine via le titre normalisé. Le cv a juste un id, pas
            # de titre. On utilise le nom de l'item lié comme fallback.
        # Item name = souvent l'adresse complète du board immeuble
        addr_full = (immeuble.get("name") or "").strip()
        if addr_full:
            address, maybe_city = extract_address_from_name(addr_full)
            city = city or maybe_city

    # Fallback : parse item name du board principal
    if not address:
        a, c = extract_address_from_name(item.get("name") or "")
        address = a or None
        city = city or c

    # Quartier (board principal) → city si pas déjà set
    quartier = get_text(item, COL_QUARTIER)
    if quartier and not city:
        city = quartier

    # Owner depuis le board Propriétaire lié
    owner_name: Optional[str] = None
    owner_phone: Optional[str] = None
    owner_email: Optional[str] = None
    owner_neq: Optional[str] = None
    if proprio is not None:
        owner_name = (proprio.get("name") or "").strip() or None
        # Heuristique : extraire phone/email/neq des column_values
        for cv in proprio.get("column_values", []):
            t = (cv.get("text") or "").strip()
            if not t:
                continue
            # Détecte par contenu : tel = 10 chiffres, email = @,
            # NEQ = 10 chiffres tous numériques
            digits_only = re.sub(r"\D", "", t)
            if "@" in t and "." in t and not owner_email:
                owner_email = t
            elif (
                len(digits_only) == 10
                and digits_only == t.replace("-", "").replace(" ", "")
                .replace("(", "").replace(")", "").replace(".", "")
                and not owner_neq
            ):
                # 10 chiffres seulement → soit téléphone, soit NEQ
                # Heuristique : si commence par 1 ou 9 → NEQ Québec
                if digits_only[0] in ("1", "9") and not owner_neq:
                    owner_neq = digits_only
                elif not owner_phone:
                    owner_phone = t
            elif len(digits_only) >= 7 and not owner_phone:
                owner_phone = t

    if owner_neq:
        owner_kind = ProspectionOwnerKind.CORPORATION.value
    elif owner_name:
        owner_kind = ProspectionOwnerKind.PARTICULIER.value
    else:
        owner_kind = ProspectionOwnerKind.INCONNU.value

    # Score Monday → notre score (cap 100)
    score_raw = parse_float(get_text(item, COL_SCORE))
    score = (
        max(0, min(100, int(score_raw))) if score_raw is not None else 0
    )

    # Date last contact
    last_contact = parse_date(get_text(item, COL_DATE_LAST_CONTACT))
    if last_contact is None:
        last_contact = parse_date(get_text(item, COL_DATE_LAST_CALL))

    # Notes : combine notes + résultat appel + source
    parts: List[str] = []
    notes = get_text(item, COL_NOTES)
    if notes:
        parts.append(notes)
    resultat = get_text(item, COL_RESULTAT)
    if resultat:
        parts.append(f"Dernier résultat appel : {resultat}")
    source = get_text(item, COL_SOURCE)
    if source:
        parts.append(f"Source : {source}")
    notes_combined = "\n".join(parts) if parts else None

    name = item.get("name") or address or "Lead Monday"

    return {
        "name": name[:255],
        "kind": ProspectionLeadKind.MULTILOGEMENT.value,  # défaut
        "address": address,
        "city": city,
        "postal_code": postal,
        "notes": notes_combined,
        "status": map_status(get_text(item, COL_ETAPE)),
        "priority": parse_priority_from_score(score_raw),
        "matricule": matricule,
        "nb_logements": nb_log,
        "annee_construction": annee,
        "valeur_fonciere": valeur,
        "owner_kind": owner_kind,
        "owner_name": owner_name,
        "owner_phone": owner_phone,
        "owner_email": owner_email,
        "owner_neq": owner_neq,
        "owner_address": None,
        "score": score,
        "contact_attempts_count": parse_int(
            get_text(item, COL_NB_APPELS)
        )
        or 0,
        "last_contacted_at": last_contact,
        "monday_item_id": str(item["id"]),
    }


# --------------------------- Main ---------------------------


async def cmd_inspect(token: str) -> int:
    meta = await fetch_board_meta(BOARD_ID, token)
    print(f"\n=== Board : {meta.get('name')} (id={meta.get('id')}) ===\n")
    print("Colonnes :")
    for col in meta.get("columns", []):
        print(
            f"  [{col.get('id'):25}] {col.get('type'):20} {col.get('title')}"
        )
    print()
    items = await fetch_all_items(BOARD_ID, token)
    print(f"Total items : {len(items)}")
    if items:
        first = items[0]
        print(
            f"\nExemple — Item « {first.get('name')} » "
            f"(id={first['id']}) :"
        )
        for cv in first.get("column_values", []):
            text = cv.get("text") or ""
            text = (text[:60] + "…") if len(text) > 60 else text
            print(f"  [{cv.get('id'):25}] = {repr(text)}")

        # Liste les statuts uniques sur tout le board (utile pour
        # vérifier le mapping de map_status())
        statuts = set()
        for it in items:
            s = get_text(it, COL_ETAPE)
            if s:
                statuts.add(s)
        print(f"\nÉtapes uniques observées sur les {len(items)} items :")
        for s in sorted(statuts):
            print(f"  · {s!r:40} → {map_status(s)}")
    print()
    return 0


async def cmd_import(
    token: str, dry_run: bool, reset: bool
) -> int:
    log.info("Chargement des items du board principal…")
    items = await fetch_all_items(BOARD_ID, token)
    log.info("  → %d items à importer", len(items))

    # Récupère les item_ids liés (proprio + immeuble) sur l'ensemble
    proprio_ids: List[str] = []
    immeuble_ids: List[str] = []
    for it in items:
        proprio_ids.extend(get_linked_ids(it, COL_PROPRIO_REL))
        immeuble_ids.extend(get_linked_ids(it, COL_IMMEUBLE_REL))
    proprio_ids = list(set(proprio_ids))
    immeuble_ids = list(set(immeuble_ids))
    log.info(
        "  → %d propriétaires liés, %d immeubles liés",
        len(proprio_ids),
        len(immeuble_ids),
    )

    log.info("Chargement des proprios + immeubles liés…")
    proprios = await fetch_items_by_ids(proprio_ids, token)
    immeubles = await fetch_items_by_ids(immeuble_ids, token)

    payloads: List[Dict[str, Any]] = []
    for it in items:
        prop_id = (get_linked_ids(it, COL_PROPRIO_REL) or [None])[0]
        imm_id = (get_linked_ids(it, COL_IMMEUBLE_REL) or [None])[0]
        proprio = proprios.get(prop_id) if prop_id else None
        immeuble = immeubles.get(imm_id) if imm_id else None
        payloads.append(build_lead_payload(it, proprio, immeuble))

    if dry_run:
        log.info("=== DRY-RUN — aperçu des 5 premiers payloads ===")
        for p in payloads[:5]:
            log.info(
                json.dumps(p, indent=2, ensure_ascii=False, default=str)
            )
        log.info(
            "Total : %d payloads. Aucune écriture DB.", len(payloads)
        )
        return 0

    async with AsyncSessionLocal() as db:
        if reset:
            log.info("RESET : suppression des leads avec monday_item_id…")
            await db.execute(
                delete(ProspectionLead).where(
                    ProspectionLead.monday_item_id.is_not(None)
                )
            )
            await db.commit()

        existing_rows = (
            await db.execute(
                select(ProspectionLead).where(
                    ProspectionLead.monday_item_id.is_not(None)
                )
            )
        ).scalars().all()
        by_mid = {r.monday_item_id: r for r in existing_rows}

        inserted = 0
        updated = 0
        for p in payloads:
            mid = p["monday_item_id"]
            existing = by_mid.get(mid)
            if existing:
                for k, v in p.items():
                    setattr(existing, k, v)
                apply_score(existing)
                updated += 1
            else:
                lead = ProspectionLead(**p)
                apply_score(lead)
                db.add(lead)
                inserted += 1
        await db.flush()
        await db.commit()
        log.info(
            "✓ Import terminé : %d insérés, %d mis à jour.",
            inserted,
            updated,
        )
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Inspecte la structure du board sans importer.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Génère les payloads sans écrire en DB.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Efface les leads importés précédemment avant import.",
    )
    args = parser.parse_args()

    token = os.environ.get("MONDAY_API_TOKEN") or os.environ.get(
        "monday_api_token"
    )
    if not token:
        log.error(
            "MONDAY_API_TOKEN non défini. Set la variable et relance."
        )
        return 1

    if args.inspect:
        return await cmd_inspect(token)
    return await cmd_import(token, args.dry_run, args.reset)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
