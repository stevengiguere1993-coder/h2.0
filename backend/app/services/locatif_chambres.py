"""Chambres et tri des numéros de logement — retours partenaires
2026-09-28 (Gestion immobilière).

1. ``compter_chambres`` : un logement loué EN CHAMBRES (colocation par
   chambre) compte pour ses chambres, pas pour une seule porte. Pour
   chaque immeuble : nombre de logements loués en chambres, total de
   chambres et chambres occupées. Même règle partout (vue d'ensemble du
   pôle, fiche immeuble) — sections miroir identiques.
2. ``cle_tri_numero`` : tri NATUREL des numéros (« quand on entre 1-2-3,
   le 10 se plaçait après le 1 et pas après le 9 ») : 1, 2, 9, 10, 11,
   101-A, 101-B, A, B.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.immobilier import Bail, BailStatus, Logement, LogementStatus

_RE_NOMBRES = re.compile(r"(\d+)")


def cle_tri_numero(numero: Optional[str]) -> tuple:
    """Clé de tri naturel : les suites de chiffres se comparent en
    nombres, le reste en texte (casse ignorée). « 04 » ≡ « 4 »."""
    s = (numero or "").strip().lower()
    cle: List[tuple] = []
    for part in _RE_NOMBRES.split(s):
        if not part:
            continue
        if part.isdigit():
            cle.append((0, int(part), ""))
        else:
            # Espaces ignorés : « 8906 - C » et « 8906-C » se classent
            # au même endroit (même règle que la détection de doublons).
            cle.append((1, 0, re.sub(r"\s+", "", part)))
    return tuple(cle) if cle else ((1, 0, ""),)


def trier_par_numero(items: Iterable[Any], attr: str = "numero") -> List[Any]:
    """Trie des objets (ou dicts) par leur numéro de logement, ordre naturel."""

    def _num(x: Any) -> Optional[str]:
        if isinstance(x, dict):
            return x.get(attr)
        return getattr(x, attr, None)

    return sorted(items, key=lambda x: cle_tri_numero(_num(x)))


async def compter_chambres(
    db: AsyncSession, immeubles: Iterable[Any]
) -> Dict[int, Dict[str, int]]:
    """{immeuble_id: {"log": logements loués en chambres, "tot": chambres,
    "occ": chambres occupées}} — seulement les immeubles qui en ont.

    Total d'un logement = son nombre de chambres (à défaut, ses baux
    actifs — on ne montre jamais plus d'occupées que de chambres).
    Occupées : baux actifs (gestion interne) ; en gestion externe (pas de
    baux chez nous), toutes si le logement est marqué occupé, sinon 0.
    Les logements hors location sont ignorés, comme pour les portes."""
    imms = list(immeubles)
    ids = [i.id for i in imms]
    if not ids:
        return {}
    externes = {i.id for i in imms if getattr(i, "gestion_externe", False)}
    logs = (
        await db.execute(
            select(Logement).where(
                Logement.immeuble_id.in_(ids),
                Logement.location_en_chambres.is_(True),
                Logement.status != LogementStatus.HORS_LOC.value,
            )
        )
    ).scalars().all()
    if not logs:
        return {}
    baux = dict(
        (
            await db.execute(
                select(Bail.logement_id, func.count(Bail.id))
                .where(
                    Bail.logement_id.in_([lg.id for lg in logs]),
                    Bail.status == BailStatus.ACTIF.value,
                )
                .group_by(Bail.logement_id)
            )
        ).all()
    )
    out: Dict[int, Dict[str, int]] = {}
    for lg in logs:
        actifs = int(baux.get(lg.id, 0))
        total = max(int(lg.nb_chambres or 0), actifs)
        if lg.immeuble_id in externes:
            occ = total if lg.status == LogementStatus.OCCUPE.value else 0
        else:
            occ = min(actifs, total)
        d = out.setdefault(lg.immeuble_id, {"log": 0, "tot": 0, "occ": 0})
        d["log"] += 1
        d["tot"] += total
        d["occ"] += occ
    return out


__all__ = ["cle_tri_numero", "compter_chambres", "trier_par_numero"]
