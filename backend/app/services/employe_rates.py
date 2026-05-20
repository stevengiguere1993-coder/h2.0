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


def resolve_real_cost(
    periods: list[RatePeriod],
    on_date: Optional[date],
    emp: Optional[Employe],
    avg_rate: float,
) -> float:
    """Coût horaire réel à appliquer à un punch daté `on_date`.

    1. Si l'employé a un historique de taux → on prend la période
       en vigueur à `on_date`.
    2. Sinon → on retombe sur les taux COURANTS de l'employé
       (rétrocompat : employé sans aucun changement documenté).
    3. Sinon → taux moyen équipe.
    """
    if periods and on_date is not None:
        p = _period_for_date(periods, on_date)
        if p is not None:
            return real_cost(
                p.hourly_rate, p.cnesst_rate, p.ccq_rate, p.is_ccq
            )
    if emp is not None:
        base = float(emp.hourly_rate or avg_rate)
        cnesst = float(emp.cnesst_rate or 0)
        ccq = float(emp.ccq_rate or 0)
        return real_cost(base, cnesst, ccq, bool(emp.is_ccq))
    return round(float(avg_rate), 2)
