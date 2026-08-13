"""TRI réalisé (XIRR) — flux datés réels.

Convention (point de vue de l'INVESTISSEUR) :
- apport          → flux NÉGATIF (argent qui sort de sa poche)
- remboursement / dividende / sortie → flux POSITIF
- valeur terminale (valeur actuelle des parts) → flux POSITIF daté
  d'aujourd'hui.

Résolution par Newton-Raphson avec repli en bissection — robuste aux
cas dégénérés (retourne None plutôt que d'exploser : tous les flux du
même signe, durée nulle, non-convergence).
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Optional


def xirr(flows: Iterable[tuple[date, float]]) -> Optional[float]:
    """TRI annualisé (fraction, ex. 0.412 = 41,2 %) ou None.

    `flows` : couples (date, montant) — au moins un négatif et un
    positif, sinon None.
    """
    fl = [(d, float(m)) for d, m in flows if m]
    if len(fl) < 2:
        return None
    if not any(m < 0 for _, m in fl) or not any(m > 0 for _, m in fl):
        return None
    fl.sort(key=lambda x: x[0])
    t0 = fl[0][0]
    # Années fractionnaires depuis le premier flux.
    times = [((d - t0).days) / 365.25 for d, _ in fl]
    if times[-1] <= 0:
        return None
    amounts = [m for _, m in fl]

    def npv(rate: float) -> float:
        return sum(
            m / (1.0 + rate) ** t for m, t in zip(amounts, times)
        )

    def dnpv(rate: float) -> float:
        return sum(
            -t * m / (1.0 + rate) ** (t + 1.0)
            for m, t in zip(amounts, times)
            if t > 0
        )

    # Newton depuis 10 %.
    rate = 0.1
    for _ in range(60):
        try:
            f = npv(rate)
            df = dnpv(rate)
        except (OverflowError, ZeroDivisionError):
            break
        if abs(df) < 1e-12:
            break
        step = f / df
        new_rate = rate - step
        if new_rate <= -0.9999:
            new_rate = (rate - 0.9999) / 2.0
        if abs(new_rate - rate) < 1e-9:
            rate = new_rate
            if abs(npv(rate)) < 1e-6:
                return rate
            break
        rate = new_rate
    else:
        if abs(npv(rate)) < 1e-6:
            return rate

    # Repli : bissection sur [-0.9999, 10] (−99,99 % à +1000 %/an).
    lo, hi = -0.9999, 10.0
    try:
        f_lo, f_hi = npv(lo), npv(hi)
    except (OverflowError, ZeroDivisionError):
        return None
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        try:
            f_mid = npv(mid)
        except (OverflowError, ZeroDivisionError):
            return None
        if abs(f_mid) < 1e-7:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0
