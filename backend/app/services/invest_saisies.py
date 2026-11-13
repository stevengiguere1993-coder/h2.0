"""Portail Investisseur — saisies MANUELLES d'un investisseur
(Steven, 2026-11-13).

Deux choses que QuickBooks ne sait pas :

1. **Apports hors QuickBooks** : capital versé avant que la compagnie
   passe à QuickBooks (Éric Brabant et Vincent Clark, 150 000 $ chacun,
   affichaient 0 $). Ce sont des ``InvestFlux`` de source
   ``hors_qbo`` : la synchro QuickBooks ne remplace QUE les flux
   ``qbo`` (``invest_qbo_sync``), et le relevé, qui prend le solde des
   avances QuickBooks comme capital actuel, y AJOUTE le net de ces
   flux (``net_hors_qbo``). Ils nourrissent le TRI comme les autres.
2. **Prêts à la compagnie** (``InvestPret``) : montant, taux annuel,
   intérêt SIMPLE mensuel = montant × taux / 12, couru = mensuel ×
   mois complets écoulés depuis le prêt (jusqu'au remboursement s'il
   est daté). Un prêt n'est pas du capital : il ne touche ni aux
   parts, ni à l'équité, ni au TRI.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invest_portal import InvestFlux, InvestFluxType, InvestPret

#: Source des flux saisis à la main, hors QuickBooks.
SOURCE_HORS_QBO = "hors_qbo"


def mois_complets(debut: date, fin: date) -> int:
    """Mois complets entre deux dates (15 jan → 14 mars = 1 ;
    15 jan → 15 mars = 2). 0 si ``fin`` ≤ ``debut``."""
    if fin <= debut:
        return 0
    n = (fin.year - debut.year) * 12 + (fin.month - debut.month)
    if fin.day < debut.day:
        n -= 1
    return max(0, n)


def interet_mensuel(montant: float, taux_annuel_pct: float) -> float:
    return round(float(montant or 0) * float(taux_annuel_pct or 0) / 100 / 12, 2)


def pret_payload(p: InvestPret, aujourdhui: Optional[date] = None) -> dict:
    today = aujourdhui or date.today()
    montant = float(p.montant or 0)
    taux = float(p.taux_annuel_pct or 0)
    mensuel = interet_mensuel(montant, taux)
    fin = p.date_remboursement or today
    nb_mois = mois_complets(p.date_pret, min(fin, today))
    en_cours = p.date_remboursement is None or p.date_remboursement > today
    return {
        "id": p.id,
        "entreprise_id": p.entreprise_id,
        "user_id": p.user_id,
        "montant": round(montant, 2),
        "taux_annuel_pct": round(taux, 3),
        "date_pret": p.date_pret.isoformat(),
        "date_remboursement": (
            p.date_remboursement.isoformat() if p.date_remboursement else None
        ),
        "note": p.note,
        "en_cours": en_cours,
        "interet_mensuel": mensuel,
        "interet_annuel": round(montant * taux / 100, 2),
        "nb_mois": nb_mois,
        "interets_courus": round(mensuel * nb_mois, 2),
    }


def resume_prets(prets: Iterable[dict]) -> dict:
    """Totaux d'une liste de ``pret_payload`` : seuls les prêts EN
    COURS comptent dans le solde prêté et l'intérêt mensuel."""
    prets = list(prets)
    actifs = [p for p in prets if p["en_cours"]]
    return {
        "prets_en_cours": round(sum(p["montant"] for p in actifs), 2),
        "interets_mensuels": round(sum(p["interet_mensuel"] for p in actifs), 2),
        "interets_courus": round(sum(p["interets_courus"] for p in prets), 2),
    }


async def prets_de(
    db: AsyncSession, user_id: int, entreprise_id: Optional[int] = None
) -> list[dict]:
    if not user_id:
        return []
    q = select(InvestPret).where(InvestPret.user_id == user_id)
    if entreprise_id is not None:
        q = q.where(InvestPret.entreprise_id == entreprise_id)
    rows = (
        await db.execute(q.order_by(InvestPret.date_pret, InvestPret.id))
    ).scalars().all()
    return [pret_payload(p) for p in rows]


def net_hors_qbo(flux: Iterable[InvestFlux]) -> float:
    """Capital encore investi d'après les flux hors QuickBooks :
    apports − remboursements − sorties (les distributions ne
    remboursent pas le capital)."""
    total = 0.0
    for f in flux:
        if f.source != SOURCE_HORS_QBO:
            continue
        m = float(f.montant or 0)
        if f.type == InvestFluxType.APPORT.value:
            total += m
        elif f.type in (
            InvestFluxType.REMBOURSEMENT.value,
            InvestFluxType.SORTIE.value,
        ):
            total -= m
    return round(total, 2)


def flux_payload(f: InvestFlux) -> dict:
    return {
        "id": f.id,
        "type": f.type,
        "montant": float(f.montant),
        "date_flux": f.date_flux.isoformat(),
        "note": f.note,
        "source": f.source,
    }
