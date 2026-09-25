"""Résolution du taux horaire effectif d'un employé à une date donnée.

Cœur de l'historisation des salaires : un punch daté D doit être
coûté au taux en vigueur à D, pas au taux courant de l'employé.

Usage typique (costing de rentabilité d'un projet) ::

    periods = await load_rate_periods(db, employe_ids)
    cost = resolve_real_cost(
        periods.get(emp.id, []), punch_date, emp, avg_rate
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employe import Employe
from app.models.employe_rate_history import EmployeRateHistory


@dataclass
class RatePeriod:
    """Une période de taux : s'applique à partir de `effective_date`."""

    effective_date: date
    hourly_rate: float
    billing_rate: Optional[float]
    cnesst_rate: float
    ccq_rate: float
    is_ccq: bool
    #: Taux de base sous régime CCQ (None = hourly_rate).
    hourly_rate_ccq: Optional[float] = None


#: Régimes d'un punch (retour Phil 2026-09-26). Le coût suit le régime du
#: punch ; ``None`` (punch d'avant la règle) suit la fiche employé.
REGIME_CCQ = "ccq"
REGIME_HORS_DECRET = "hors_decret"
REGIMES = (REGIME_CCQ, REGIME_HORS_DECRET)


def regime_effectif(
    periods: list["RatePeriod"], on_date: Optional[date], emp: Optional[Employe], regime: Optional[str]
) -> str:
    """Régime à appliquer : celui du punch s'il est posé, sinon celui de
    la fiche employé à la date (historique), sinon hors décret."""
    if regime in REGIMES:
        return regime
    if periods and on_date is not None:
        p = _period_for_date(periods, on_date)
        if p is not None:
            return REGIME_CCQ if p.is_ccq else REGIME_HORS_DECRET
    if emp is not None:
        return REGIME_CCQ if bool(emp.is_ccq) else REGIME_HORS_DECRET
    return REGIME_HORS_DECRET


def real_cost(
    base: float, cnesst: float, ccq: float, is_ccq: bool
) -> float:
    """Coût horaire réel = base × (1 + CNESST + CCQ si actif).
    Les taux CNESST/CCQ sont en DÉCIMAL (0.0216 = 2,16 %)."""
    eff_ccq = ccq if is_ccq else 0.0
    return round(
        float(base or 0) * (1.0 + float(cnesst or 0) + float(eff_ccq or 0)),
        2,
    )


async def load_rate_periods(
    db: AsyncSession, employe_ids: Iterable[int]
) -> dict[int, list[RatePeriod]]:
    """Précharge l'historique des taux pour un lot d'employés.
    Retourne employe_id → liste de RatePeriod triée par date croissante."""
    ids = list({int(i) for i in employe_ids if i is not None})
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(EmployeRateHistory)
            .where(EmployeRateHistory.employe_id.in_(ids))
            .order_by(EmployeRateHistory.effective_date.asc())
        )
    ).scalars().all()
    out: dict[int, list[RatePeriod]] = {}
    for r in rows:
        out.setdefault(r.employe_id, []).append(
            RatePeriod(
                effective_date=r.effective_date,
                hourly_rate=float(r.hourly_rate or 0),
                billing_rate=(
                    float(r.billing_rate)
                    if r.billing_rate is not None
                    else None
                ),
                cnesst_rate=float(r.cnesst_rate or 0),
                ccq_rate=float(r.ccq_rate or 0),
                is_ccq=bool(r.is_ccq),
                hourly_rate_ccq=(
                    float(r.hourly_rate_ccq)
                    if getattr(r, "hourly_rate_ccq", None) is not None
                    else None
                ),
            )
        )
    return out


def _period_for_date(
    periods: list[RatePeriod], on_date: date
) -> Optional[RatePeriod]:
    """Période en vigueur à `on_date` : la plus récente dont
    `effective_date <= on_date`. Si `on_date` précède toutes les
    périodes, on retourne la PLUS ANCIENNE (= taux d'origine, la
    baseline couvre tout le passé)."""
    if not periods:
        return None
    chosen: Optional[RatePeriod] = None
    for p in periods:  # triées asc
        if p.effective_date <= on_date:
            chosen = p
        else:
            break
    return chosen or periods[0]


def resolve_base_rate(
    periods: list[RatePeriod],
    on_date: Optional[date],
    emp: Optional[Employe],
    regime: Optional[str] = None,
) -> Optional[float]:
    """Taux horaire de BASE (ce qu'on paie à l'employé, avant primes
    CNESST/CCQ) à `on_date` pour le régime donné : ``hourly_rate_ccq``
    (sinon ``hourly_rate``) sous CCQ, ``hourly_rate`` hors décret. Sert
    à la paie."""
    # Le taux CCQ ne s'applique qu'à un punch EXPLICITEMENT « ccq » : un
    # punch d'avant la règle (None) reste payé au taux courant (pas de
    # réécriture rétroactive de la paie ni des coûts).
    explicite_ccq = regime == REGIME_CCQ
    if periods and on_date is not None:
        p = _period_for_date(periods, on_date)
        if p is not None:
            if explicite_ccq:
                t = _taux_ccq_periode(p, periods, emp)
                if t is not None:
                    return t
            return float(p.hourly_rate)
    if emp is not None:
        if explicite_ccq and getattr(emp, "hourly_rate_ccq", None) is not None:
            return float(emp.hourly_rate_ccq)
        return float(emp.hourly_rate) if emp.hourly_rate is not None else None
    return None


def _taux_ccq_periode(
    p: RatePeriod, periods: list[RatePeriod], emp: Optional[Employe]
) -> Optional[float]:
    """Taux CCQ d'une période ; si la période n'en a pas et que c'est la
    plus récente, le taux CCQ saisi sur la fiche (PATCH sans palier)
    fait foi."""
    if p.hourly_rate_ccq is not None:
        return float(p.hourly_rate_ccq)
    if periods and p is periods[-1] and emp is not None and getattr(emp, "hourly_rate_ccq", None) is not None:
        return float(emp.hourly_rate_ccq)
    return None


def resolve_real_cost(
    periods: list[RatePeriod],
    on_date: Optional[date],
    emp: Optional[Employe],
    avg_rate: float,
    regime: Optional[str] = None,
) -> float:
    """Coût horaire réel à appliquer à un punch daté `on_date`.

    1. Si l'employé a un historique de taux → on prend la période
       en vigueur à `on_date`.
    2. Sinon → on retombe sur les taux COURANTS de l'employé
       (rétrocompat : employé sans aucun changement documenté).
    3. Sinon → taux moyen équipe.

    ``regime`` (2026-09-26) : « ccq » → taux de base CCQ (sinon le taux
    courant) + majoration CCQ ; « hors_decret » → taux courant, sans
    majoration CCQ ; None → suit la fiche employé à la date (comme avant).
    La CNESST s'applique dans tous les cas.
    """
    reg = regime_effectif(periods, on_date, emp, regime)
    is_ccq = reg == REGIME_CCQ          # majoration CCQ (fiche ou punch)
    explicite_ccq = regime == REGIME_CCQ  # taux de base CCQ : punch explicite seulement
    if periods and on_date is not None:
        p = _period_for_date(periods, on_date)
        if p is not None:
            base = p.hourly_rate
            if explicite_ccq:
                t = _taux_ccq_periode(p, periods, emp)
                if t is not None:
                    base = t
            return real_cost(base, p.cnesst_rate, p.ccq_rate, is_ccq)
    if emp is not None:
        base = float(emp.hourly_rate or avg_rate)
        if explicite_ccq and getattr(emp, "hourly_rate_ccq", None) is not None:
            base = float(emp.hourly_rate_ccq)
        cnesst = float(emp.cnesst_rate or 0)
        ccq = float(emp.ccq_rate or 0)
        return real_cost(base, cnesst, ccq, is_ccq)
    return round(float(avg_rate), 2)
