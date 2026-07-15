"""Calculs hypothécaires partagés — balance amortie automatique.

La balance d'une hypothèque « s'update toute seule » (retour Phil
2026-07-10) : à partir du montant initial, du taux, de l'amortissement,
de la composition et de la date de début, on calcule la balance
théorique au jour J selon le tableau d'amortissement canadien :

    i  = taux mensuel effectif (composition semi-annuelle ou mensuelle)
    k  = mois complets écoulés depuis la date de début
    B  = P·(1+i)^k − PMT·((1+i)^k − 1)/i

Une balance SAISIE À LA MAIN a toujours priorité (elle reflète des
remboursements anticipés que le calcul ne connaît pas).
"""

from __future__ import annotations

from datetime import date
from typing import Optional


def taux_mensuel(taux_pct: float, composition: Optional[str]) -> float:
    """Taux mensuel effectif : composition semi-annuelle (résidentiel
    canadien, défaut) ou mensuelle (commercial/variable)."""
    if (composition or "semi") == "mensuelle":
        return taux_pct / 100.0 / 12.0
    return (1.0 + taux_pct / 100.0 / 2.0) ** (2.0 / 12.0) - 1.0


def _mois_ecoules(date_debut: date, aujourd_hui: date) -> int:
    mois = (aujourd_hui.year - date_debut.year) * 12 + (
        aujourd_hui.month - date_debut.month
    )
    if aujourd_hui.day < date_debut.day:
        mois -= 1
    return max(0, mois)


def balance_calculee(
    *,
    montant_initial: Optional[float],
    taux_pct: Optional[float],
    amortissement_mois: Optional[int],
    composition: Optional[str],
    date_debut: Optional[date],
    paiement_mensuel: Optional[float] = None,
    aujourd_hui: Optional[date] = None,
) -> Optional[float]:
    """Balance théorique au jour J, ou None si les intrants manquent."""
    if (
        montant_initial is None
        or montant_initial <= 0
        or taux_pct is None
        or not amortissement_mois
        or amortissement_mois <= 0
        or date_debut is None
    ):
        return None
    aujourd_hui = aujourd_hui or date.today()
    k = min(_mois_ecoules(date_debut, aujourd_hui), amortissement_mois)
    if k <= 0:
        return round(float(montant_initial), 2)

    p = float(montant_initial)
    if taux_pct <= 0:
        pmt = paiement_mensuel or (p / amortissement_mois)
        return round(max(0.0, p - pmt * k), 2)

    i = taux_mensuel(float(taux_pct), composition)
    pmt = (
        float(paiement_mensuel)
        if paiement_mensuel
        else p * i / (1.0 - (1.0 + i) ** (-amortissement_mois))
    )
    facteur = (1.0 + i) ** k
    balance = p * facteur - pmt * (facteur - 1.0) / i
    return round(max(0.0, balance), 2)


def balance_calculee_de(hyp, aujourd_hui: Optional[date] = None) -> Optional[float]:
    """Balance théorique d'un objet Hypotheque (colonnes SQLAlchemy)."""
    return balance_calculee(
        montant_initial=(
            float(hyp.montant_initial)
            if hyp.montant_initial is not None
            else None
        ),
        taux_pct=float(hyp.taux_pct) if hyp.taux_pct is not None else None,
        amortissement_mois=hyp.amortissement_mois,
        composition=hyp.composition_interets,
        date_debut=hyp.date_debut,
        paiement_mensuel=(
            float(hyp.paiement_mensuel)
            if hyp.paiement_mensuel is not None
            else None
        ),
        aujourd_hui=aujourd_hui,
    )


def balance_effective(hyp, aujourd_hui: Optional[date] = None) -> float:
    """Balance à utiliser dans l'équité/les financials : la balance
    SAISIE prime, sinon la balance CALCULÉE, sinon le montant initial."""
    if hyp.balance_actuelle is not None:
        return float(hyp.balance_actuelle)
    calc = balance_calculee_de(hyp, aujourd_hui)
    if calc is not None:
        return calc
    return float(hyp.montant_initial or 0)
