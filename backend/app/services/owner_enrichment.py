"""Enrichissement automatique des propriétaires détectés sur EvalWeb.

Pour chaque propriétaire parsé depuis le rôle d'évaluation :
1. Détecte s'il s'agit d'une corporation (statut « Personne morale »
   ou suffixe Inc./Ltée/etc. dans le nom).
2. Si corp → lookup REQ par nom dans `req_companies` pour récupérer
   NEQ, statut juridique, adresse de siège, téléphone.
3. Pour TOUS les owners (corp ou personne physique) → lookup Canada411
   avec le nom + ville pour récupérer un téléphone.
4. Augmente le dict owner avec : `phone`, `phone_source`, `req_neq`,
   `req_address`, `req_telephone`, `req_status`.

Le résultat enrichi est stocké dans `mtl_property_units.owners_json`
et propagé au lead lors de la conversion.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


# Suffixes corporatifs québécois courants. Si le nom de l'owner se
# termine par un de ceux-là, c'est presque sûr que c'est une corp.
_CORP_SUFFIXES = re.compile(
    r"""\b(?:
        inc(?:orpor[ée]e?)?\.?|
        ltée\.?|ltée|ltd\.?|limit[ée]e?|
        s\.?e\.?n\.?c\.?(?:\.?r\.?l\.?)?|
        corp(?:oration)?\.?|
        company|cie|
        soci[ée]t[ée]|
        l\.?l\.?c\.?|
        co\.|
        gie|
        e[nt]reprises?|
        groupe|
        holdings?|
        immeubles?|
        immobilier|
        gestion|
        invest(?:issements?)?
    )\b\.?$""",
    re.IGNORECASE | re.VERBOSE,
)


def is_corporation(owner: dict) -> bool:
    """True si l'owner ressemble à une corporation."""
    statut = (owner.get("statut") or "").lower()
    if "morale" in statut:
        return True
    name = (owner.get("name") or "").strip()
    if _CORP_SUFFIXES.search(name):
        return True
    # Nom genre « 9123-4567 QUÉBEC INC. » → toujours corp
    if re.search(r"^\d{4}-\d{4}\b", name):
        return True
    return False


def _city_from_address(address: Optional[str]) -> Optional[str]:
    """Extrait la ville d'une adresse postale type EvalWeb.
    Format typique : « 450 CH DU GOLF, VERDUN QUEBEC, H3E 1A8 »."""
    if not address:
        return None
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) < 2:
        return None
    # 2e segment = "VERDUN QUEBEC" — on prend le 1er mot
    middle = parts[1]
    # Retire « QUEBEC », « QC » etc.
    cleaned = re.sub(
        r"\s+(quebec|qc|québec|canada|ca)\s*$",
        "",
        middle,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or None


async def _enrich_one_owner(
    db: AsyncSession, owner: dict
) -> dict:
    """Enrichit UN propriétaire avec lookups REQ + Canada411."""
    enriched = dict(owner)
    name = (owner.get("name") or "").strip()
    if not name:
        return enriched

    # 1. Si corp, lookup REQ par nom
    if is_corporation(owner):
        try:
            from app.integrations.req.companies import lookup_by_name

            results = await lookup_by_name(db, name, limit=3)
            if results:
                # On prend le 1er match
                corp = results[0]
                enriched["req_neq"] = corp.neq
                enriched["req_status"] = corp.statut
                enriched["req_forme_juridique"] = corp.forme_juridique
                enriched["req_address"] = (
                    corp.adresse if corp.adresse else None
                )
                enriched["req_ville"] = corp.ville
                enriched["req_code_postal"] = corp.code_postal
                if corp.telephone and not enriched.get("phone"):
                    enriched["phone"] = corp.telephone
                    enriched["phone_source"] = "req"
        except Exception as exc:
            log.warning(
                "REQ lookup failed pour %r: %s", name, exc
            )

    # 2. Canada411 si pas encore de téléphone
    if not enriched.get("phone"):
        try:
            from app.integrations.canada411 import lookup_by_name as c411

            city = _city_from_address(
                owner.get("postal_address")
            )
            results = await c411(name, city=city)
            if results:
                first = results[0]
                enriched["phone"] = first.get("phone")
                enriched["phone_source"] = "canada411"
                enriched["c411_address"] = first.get("address")
        except Exception as exc:
            log.warning(
                "Canada411 lookup failed pour %r: %s", name, exc
            )

    return enriched


async def enrich_owners(
    db: AsyncSession, owners: List[dict]
) -> List[dict]:
    """Enrichit tous les propriétaires en parallèle. Best-effort :
    si un lookup échoue, on garde les autres données."""
    if not owners:
        return []
    enriched = []
    for o in owners:
        try:
            e = await _enrich_one_owner(db, o)
            enriched.append(e)
        except Exception as exc:
            log.exception("enrich_one_owner failed: %s", exc)
            enriched.append(o)
    return enriched
