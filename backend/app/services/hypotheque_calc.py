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

Mode de remboursement (Phil 2026-10-04) :
- ``capital_interet`` (défaut) : tableau d'amortissement ci-dessus ;
- ``capital_seulement`` : capital / mois, sans intérêt → baisse linéaire ;
- ``interet_seulement`` (prêts privés) : les paiements ne couvrent que
  l'intérêt → le capital NE BAISSE PAS, la balance reste le montant initial.
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
    mode_remboursement: Optional[str] = None,
) -> Optional[float]:
    """Balance théorique au jour J, ou None si les intrants manquent."""
    if montant_initial is None or montant_initial <= 0:
        return None
    if (mode_remboursement or "capital_interet") == "interet_seulement":
        # Intérêts seulement : le capital reste dû en entier.
        return round(float(montant_initial), 2)
    if (
        taux_pct is None
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
    if taux_pct <= 0 or mode_remboursement == "capital_seulement":
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


#: Attribut posé sur l'objet Hypotheque par ``charger_debourses`` :
#: somme des tranches déboursées à ce jour (None = pas de tranche).
ATTR_DEBOURSE = "montant_debourse_cache"


def capital_de(hyp) -> Optional[float]:
    """Capital réellement prêté : le déboursé à ce jour si l'hypothèque
    est versée par tranches, sinon le montant initial."""
    deb = getattr(hyp, ATTR_DEBOURSE, None)
    if deb is not None:
        return float(deb)
    return float(hyp.montant_initial) if hyp.montant_initial is not None else None


async def charger_debourses(db, hyps, aujourd_hui: Optional[date] = None) -> None:
    """Pose ``montant_debourse_cache`` sur chaque hypothèque qui a des
    tranches (somme des tranches dont la date est passée). À appeler
    partout où l'on lit des hypothèques pour l'équité / le paiement."""
    from sqlalchemy import func, select

    from app.models.immobilier import HypothequeTranche

    hyps = list(hyps)
    if not hyps:
        return
    aujourd_hui = aujourd_hui or date.today()
    rows = (
        await db.execute(
            select(
                HypothequeTranche.hypotheque_id,
                func.sum(HypothequeTranche.montant),
            )
            .where(
                HypothequeTranche.hypotheque_id.in_([h.id for h in hyps]),
                HypothequeTranche.date_debourse <= aujourd_hui,
            )
            .group_by(HypothequeTranche.hypotheque_id)
        )
    ).all()
    sommes = {int(hid): float(total or 0) for hid, total in rows}
    # Une hypothèque avec des tranches toutes FUTURES = 0 déboursé.
    avec_tranches = set(
        int(x)
        for x in (
            await db.execute(
                select(HypothequeTranche.hypotheque_id)
                .where(HypothequeTranche.hypotheque_id.in_([h.id for h in hyps]))
                .distinct()
            )
        ).scalars().all()
    )
    for h in hyps:
        if h.id in avec_tranches:
            setattr(h, ATTR_DEBOURSE, round(sommes.get(h.id, 0.0), 2))
        else:
            setattr(h, ATTR_DEBOURSE, None)


def balance_calculee_de(hyp, aujourd_hui: Optional[date] = None) -> Optional[float]:
    """Balance théorique d'un objet Hypotheque (colonnes SQLAlchemy)."""
    capital = capital_de(hyp)
    if capital is not None and capital <= 0:
        return 0.0
    return balance_calculee(
        montant_initial=capital,
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
        mode_remboursement=getattr(hyp, "mode_remboursement", None),
    )


def paiement_mensuel_calcule(
    *,
    taux_pct: Optional[float],
    amortissement_mois: Optional[int],
    principal: Optional[float],
    composition: Optional[str],
    mode_remboursement: Optional[str] = None,
) -> Optional[float]:
    """Paiement mensuel selon le mode : amorti (capital + intérêts),
    capital seulement (principal / n) ou intérêts seulement (principal × i).
    Même math que le formulaire de la fiche immeuble."""
    if principal is None or principal <= 0:
        return None
    mode = mode_remboursement or "capital_interet"
    n = int(amortissement_mois or 0)
    if mode == "interet_seulement":
        if taux_pct is None:
            return None
        return round(float(principal) * taux_mensuel(float(taux_pct), composition), 2)
    if n <= 0:
        return None
    if mode == "capital_seulement" or taux_pct is None or taux_pct <= 0:
        if taux_pct is None and mode != "capital_seulement":
            return None
        return round(float(principal) / n, 2)
    i = taux_mensuel(float(taux_pct), composition)
    if i <= 0:
        return round(float(principal) / n, 2)
    return round(float(principal) * i / (1.0 - (1.0 + i) ** (-n)), 2)


def balance_effective(hyp, aujourd_hui: Optional[date] = None) -> float:
    """Balance à utiliser dans l'équité/les financials : la balance
    SAISIE prime, sinon la balance CALCULÉE, sinon le montant initial."""
    if hyp.balance_actuelle is not None:
        return float(hyp.balance_actuelle)
    calc = balance_calculee_de(hyp, aujourd_hui)
    if calc is not None:
        return calc
    return float(capital_de(hyp) or 0)
