"""Import one-shot Monday → Prospection (board 7714284220).

Importe le tableau « CRM Prospection » de Monday dans la table
`prospection_leads` de h2.0. Chaque item Monday devient un
ProspectionLead (1 lead = 1 immeuble), avec mapping intelligent
des colonnes vers nos champs.

Le script est tolérant : il essaie de matcher les colonnes par
nom plutôt que par ID hardcodé (puisque les IDs Monday peuvent
varier). Un mode --inspect imprime la structure du board pour
permettre un calibrage manuel si le matching auto rate.

Idempotent : la clé d'unicité est `monday_item_id` (string). Un
re-run = UPDATE des leads existants, INSERT des nouveaux.

Usage Render Shell :
    cd /opt/render/project/src/backend
    # 1) Inspect : voir la structure du board (colonnes + 1er item)
    python -m scripts.import_monday_prospection --inspect

    # 2) Dry-run : voir ce qui serait importé sans rien écrire
    python -m scripts.import_monday_prospection --dry-run

    # 3) Import réel
    python -m scripts.import_monday_prospection

    # 4) Reset + import (efface les leads Monday précédemment importés)
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
from typing import Any, Dict, List, Optional

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


# --------------------------- Heuristics ---------------------------

# Mots-clés pour matcher les noms de colonnes Monday → notre champ.
# Ordre = priorité. Insensible aux accents/casse.
COL_HINTS: Dict[str, List[str]] = {
    "address": ["adresse", "address", "rue", "civique"],
    "city": ["ville", "city", "municipalité", "municipalite"],
    "postal_code": ["code postal", "postal", "zip"],
    "nb_logements": [
        "logement",
        "log",
        "porte",
        "doors",
        "unités",
        "unites",
    ],
    "annee_construction": [
        "année",
        "annee",
        "year",
        "construit",
        "construction",
    ],
    "valeur_fonciere": [
        "valeur fonciere",
        "valeur foncière",
        "evaluation",
        "évaluation",
        "valuation",
    ],
    "matricule": ["matricule"],
    "owner_name": ["propriétaire", "proprietaire", "owner", "nom proprio"],
    "owner_phone": [
        "téléphone",
        "telephone",
        "phone",
        "tel proprio",
        "cell",
    ],
    "owner_email": ["courriel", "email"],
    "owner_neq": ["neq"],
    "owner_address": ["adresse proprio", "mailing", "domicile"],
    "notes": ["notes", "commentaires", "remarques"],
    "status_text": ["statut", "status", "étape", "etape", "stage"],
    "kind_text": ["type", "kind", "category", "catégorie"],
    "priority_text": ["priorité", "priorite", "priority", "étoiles"],
}


def _norm(s: str) -> str:
    if not s:
        return ""
    s = "".join(
        c
        for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )
    return s.lower().strip()


def map_columns(columns_meta: List[Dict[str, Any]]) -> Dict[str, str]:
    """Pour chaque champ de notre modèle, trouve la colonne Monday
    qui matche le mieux. Retourne {our_field: monday_col_id}."""
    out: Dict[str, str] = {}
    used_ids: set = set()
    for our_field, hints in COL_HINTS.items():
        for hint in hints:
            for col in columns_meta:
                cid = col.get("id")
                title = _norm(col.get("title", ""))
                if not cid or cid in used_ids or not title:
                    continue
                if hint in title:
                    out[our_field] = cid
                    used_ids.add(cid)
                    break
            if our_field in out:
                break
    return out


# --------------------------- Status mapping ---------------------------

# Mapping flexible : Monday status text → notre enum de buy-flow.
STATUS_MAP_HINTS: List[tuple[str, str]] = [
    # (mot-clé dans le label Monday, notre status)
    ("notaire", ProspectionLeadStatus.CHEZ_NOTAIRE.value),
    ("cession", ProspectionLeadStatus.EN_CESSION.value),
    ("flip", ProspectionLeadStatus.EN_CESSION.value),
    ("nego", ProspectionLeadStatus.EN_NEGO.value),
    ("inspection", ProspectionLeadStatus.EN_INSPECTION.value),
    ("offre acceptee", ProspectionLeadStatus.OFFRE_ACCEPTEE.value),
    ("offre acceptée", ProspectionLeadStatus.OFFRE_ACCEPTEE.value),
    ("acceptee", ProspectionLeadStatus.OFFRE_ACCEPTEE.value),
    ("offre soumise", ProspectionLeadStatus.SOUMISSIONNE.value),
    ("offre", ProspectionLeadStatus.SOUMISSIONNE.value),
    ("soumis", ProspectionLeadStatus.SOUMISSIONNE.value),
    # « à contacter » DOIT venir avant « contacte » sinon match foireux
    # (substring « contacte » est dans « à contacter »).
    ("a contacter", ProspectionLeadStatus.A_CONTACTER.value),
    ("à contacter", ProspectionLeadStatus.A_CONTACTER.value),
    ("rappeler", ProspectionLeadStatus.A_CONTACTER.value),
    ("contacte", ProspectionLeadStatus.CONTACTE.value),
    ("contacté", ProspectionLeadStatus.CONTACTE.value),
    ("achete", ProspectionLeadStatus.CONVERTI.value),
    ("acheté", ProspectionLeadStatus.CONVERTI.value),
    ("cede", ProspectionLeadStatus.CONVERTI.value),
    ("cédé", ProspectionLeadStatus.CONVERTI.value),
    ("perdu", ProspectionLeadStatus.PERDU.value),
    ("refus", ProspectionLeadStatus.PERDU.value),
    ("pas vendable", ProspectionLeadStatus.PERDU.value),
    ("visite", ProspectionLeadStatus.VISITE.value),
    ("repere", ProspectionLeadStatus.A_VISITER.value),
    ("repéré", ProspectionLeadStatus.A_VISITER.value),
]


def map_status(text: Optional[str]) -> str:
    if not text:
        return ProspectionLeadStatus.A_VISITER.value
    n = _norm(text)
    for hint, status in STATUS_MAP_HINTS:
        if hint in n:
            return status
    return ProspectionLeadStatus.A_VISITER.value


KIND_MAP_HINTS: List[tuple[str, str]] = [
    ("multi", ProspectionLeadKind.MULTILOGEMENT.value),
    ("logement", ProspectionLeadKind.MULTILOGEMENT.value),
    ("plex", ProspectionLeadKind.MULTILOGEMENT.value),
    ("terrain", ProspectionLeadKind.TERRAIN.value),
    ("commercial", ProspectionLeadKind.SEMI_COMMERCIAL.value),
    ("semi", ProspectionLeadKind.SEMI_COMMERCIAL.value),
]


def map_kind(text: Optional[str]) -> str:
    if not text:
        return ProspectionLeadKind.MULTILOGEMENT.value
    n = _norm(text)
    for hint, kind in KIND_MAP_HINTS:
        if hint in n:
            return kind
    return ProspectionLeadKind.AUTRE.value


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
    out: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        cursor_arg = f', cursor: "{cursor}"' if cursor else ""
        query = (
            f"query {{ boards(ids: [{board_id}]) {{ items_page(limit: 100"
            f"{cursor_arg}) {{ cursor items {{ id name "
            "column_values { id text value type "
            "... on BoardRelationValue { linked_item_ids } "
            "} updates(limit: 50) { id body created_at } } } } }"
        )
        data = await monday_query(query, token)
        page = data["boards"][0]["items_page"]
        out.extend(page["items"])
        cursor = page.get("cursor")
        if not cursor:
            break
        await asyncio.sleep(0.5)
    return out


# --------------------------- Value extraction ---------------------------


def get_text(item: Dict[str, Any], col_id: Optional[str]) -> Optional[str]:
    if not col_id:
        return None
    for cv in item.get("column_values", []):
        if cv.get("id") == col_id:
            t = cv.get("text")
            return t.strip() if t else None
    return None


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


def parse_priority(s: Optional[str]) -> int:
    """Convert priority text (étoiles, urgent, etc.) → 1-5 int."""
    if not s:
        return 3
    n = _norm(s)
    if "5" in n or "tres haute" in n or "très haute" in n or "urgent" in n:
        return 5
    if "4" in n or "haute" in n:
        return 4
    if "2" in n or "basse" in n:
        return 2
    if "1" in n or "tres basse" in n or "très basse" in n:
        return 1
    return 3


# --------------------------- Build ---------------------------


def build_lead_payload(
    item: Dict[str, Any], col_map: Dict[str, str]
) -> Dict[str, Any]:
    """Construit un dict de payload ProspectionLead à partir d'un
    item Monday + le mapping de colonnes détecté."""
    nb_log = parse_int(get_text(item, col_map.get("nb_logements")))
    annee = parse_int(get_text(item, col_map.get("annee_construction")))
    valeur = parse_float(get_text(item, col_map.get("valeur_fonciere")))

    address = get_text(item, col_map.get("address"))
    name = item.get("name") or address or "Lead Monday"
    owner_name = get_text(item, col_map.get("owner_name"))
    owner_phone = get_text(item, col_map.get("owner_phone"))
    owner_email = get_text(item, col_map.get("owner_email"))
    owner_neq = get_text(item, col_map.get("owner_neq"))
    owner_address = get_text(item, col_map.get("owner_address"))

    # Owner kind : si NEQ → corp, sinon si nom → particulier
    if owner_neq:
        owner_kind = ProspectionOwnerKind.CORPORATION.value
    elif owner_name:
        owner_kind = ProspectionOwnerKind.PARTICULIER.value
    else:
        owner_kind = ProspectionOwnerKind.INCONNU.value

    return {
        "name": name[:255],
        "kind": map_kind(get_text(item, col_map.get("kind_text"))),
        "address": address,
        "city": get_text(item, col_map.get("city")),
        "postal_code": get_text(item, col_map.get("postal_code")),
        "notes": get_text(item, col_map.get("notes")),
        "status": map_status(get_text(item, col_map.get("status_text"))),
        "priority": parse_priority(
            get_text(item, col_map.get("priority_text"))
        ),
        "matricule": get_text(item, col_map.get("matricule")),
        "nb_logements": nb_log,
        "annee_construction": annee,
        "valeur_fonciere": valeur,
        "owner_kind": owner_kind,
        "owner_name": owner_name,
        "owner_phone": owner_phone,
        "owner_email": owner_email,
        "owner_neq": owner_neq,
        "owner_address": owner_address,
        "monday_item_id": str(item["id"]),
    }


# --------------------------- Main ---------------------------


async def cmd_inspect(token: str) -> int:
    """Imprime la structure du board + 1er item pour aider le mapping."""
    meta = await fetch_board_meta(BOARD_ID, token)
    print(f"\n=== Board : {meta.get('name')} (id={meta.get('id')}) ===\n")
    print("Colonnes :")
    for col in meta.get("columns", []):
        print(
            f"  [{col.get('id'):20}] {col.get('type'):20} {col.get('title')}"
        )
    print()
    items = await fetch_all_items(BOARD_ID, token)
    print(f"Total items : {len(items)}")
    if items:
        first = items[0]
        print(f"\nExemple — Item « {first.get('name')} » (id={first['id']}) :")
        for cv in first.get("column_values", []):
            text = cv.get("text") or ""
            text = (text[:60] + "…") if len(text) > 60 else text
            print(
                f"  [{cv.get('id'):20}] = {repr(text)}"
            )
    print()
    return 0


async def cmd_import(
    token: str, dry_run: bool, reset: bool
) -> int:
    meta = await fetch_board_meta(BOARD_ID, token)
    log.info("Board : %s (id=%s)", meta.get("name"), meta.get("id"))
    col_map = map_columns(meta.get("columns", []))
    log.info("Mapping détecté :")
    for k, v in col_map.items():
        log.info("  %s → %s", k, v)
    missing = [k for k in COL_HINTS if k not in col_map]
    if missing:
        log.warning("Colonnes non matchées (à ignorer) : %s", missing)

    items = await fetch_all_items(BOARD_ID, token)
    log.info("Items à importer : %d", len(items))

    payloads = [build_lead_payload(it, col_map) for it in items]

    if dry_run:
        log.info("=== DRY-RUN — aperçu des 3 premiers payloads ===")
        for p in payloads[:3]:
            log.info(json.dumps(p, indent=2, ensure_ascii=False))
        log.info("Total : %d payloads. Aucune écriture DB.", len(payloads))
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

        # Map des leads existants par monday_item_id
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
            "MONDAY_API_TOKEN non défini en env. "
            "Set la variable et relance."
        )
        return 1

    if args.inspect:
        return await cmd_inspect(token)
    return await cmd_import(token, args.dry_run, args.reset)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
