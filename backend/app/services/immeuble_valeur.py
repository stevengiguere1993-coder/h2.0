"""Valeur d'un immeuble : l'évaluation retenue, et sa saisie directe.

Une seule règle pour « Valeur actuelle » (fiche, aperçu de fusion,
« Modifier l'immeuble ») : l'évaluation marquée « référence » prime, la
plus récente d'abord ; sans référence, l'évaluation la plus récente toutes
catégories. « Valeur municipale » = la plus récente de type municipale. À
date égale, le plus grand identifiant l'emporte (jamais un choix au
hasard : la fiche du 9085 Millen avait deux références à la même date
après la fusion, et n'en affichait qu'une — Steven 2026-11-13).

« Dans la modification je devrais être en mesure de modifier la valeur
d'un immeuble » (Steven, même jour) : ``fixer_valeur_actuelle`` enregistre
la valeur saisie comme une NOUVELLE évaluation datée du jour (type
« marchande »), retenue comme référence. Les évaluations existantes ne
sont pas réécrites — un rapport d'évaluateur garde son montant et sa date,
l'historique reste dans l'onglet Évaluations. Une seconde saisie le même
jour corrige celle du jour au lieu d'en empiler une autre.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import select, update

from app.models.immobilier import Evaluation, EvaluationKind

#: Source des évaluations créées par « Modifier l'immeuble ».
SOURCE_SAISIE = "Saisie dans « Modifier l'immeuble »"


def aujourd_hui() -> date:
    """La date du jour à Montréal."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Toronto")).date()
    except Exception:  # noqa: BLE001 — pas de base de fuseaux : heure normale de l'Est
        return (datetime.now(timezone.utc) - timedelta(hours=5)).date()


def _cle_recente(e: Evaluation) -> tuple:
    return (e.date_evaluation, e.id or 0)


def evaluation_retenue(evals: Iterable[Evaluation]) -> Optional[Evaluation]:
    """L'évaluation qui donne la « Valeur actuelle »."""
    liste = list(evals)
    refs = [e for e in liste if e.is_reference]
    if refs:
        return max(refs, key=_cle_recente)
    return max(liste, key=_cle_recente) if liste else None


def evaluation_municipale(evals: Iterable[Evaluation]) -> Optional[Evaluation]:
    """L'évaluation municipale la plus récente."""
    munis = [e for e in evals if e.kind == EvaluationKind.MUNICIPALE.value]
    return max(munis, key=_cle_recente) if munis else None


async def evaluations_de(db, immeuble_id: int) -> list[Evaluation]:
    return list(
        (
            await db.execute(
                select(Evaluation)
                .where(Evaluation.immeuble_id == immeuble_id)
                .order_by(Evaluation.date_evaluation.desc(), Evaluation.id.desc())
            )
        ).scalars().all()
    )


async def valeurs_de(db, immeuble_id: int) -> tuple[Optional[float], Optional[float]]:
    """(valeur actuelle, valeur municipale) de l'immeuble."""
    evals = await evaluations_de(db, immeuble_id)
    ret = evaluation_retenue(evals)
    muni = evaluation_municipale(evals)
    return (
        float(ret.valeur) if ret is not None else None,
        float(muni.valeur) if muni is not None else None,
    )


def _montant(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",") + " $"


async def fixer_valeur_actuelle(
    db, immeuble_id: int, valeur: float, *, jour: Optional[date] = None
) -> Optional[Evaluation]:
    """Fait de ``valeur`` la valeur actuelle de l'immeuble. Renvoie
    l'évaluation créée ou corrigée, ou None si la valeur ne change pas.
    Ne fait pas de commit."""
    valeur = round(float(valeur), 2)
    jour = jour or aujourd_hui()
    evals = await evaluations_de(db, immeuble_id)
    retenue = evaluation_retenue(evals)
    if retenue is not None and abs(float(retenue.valeur) - valeur) < 0.005:
        return None
    du_jour = next(
        (
            e
            for e in evals
            if e.date_evaluation == jour and (e.source or "") == SOURCE_SAISIE
        ),
        None,
    )
    if du_jour is not None:
        du_jour.valeur = valeur
        cible = du_jour
    else:
        note = None
        if retenue is not None:
            note = (
                f"Valeur précédente : {_montant(float(retenue.valeur))} "
                f"(évaluation du {retenue.date_evaluation.isoformat()})."
            )
        cible = Evaluation(
            immeuble_id=immeuble_id,
            kind=EvaluationKind.MARCHANDE.value,
            valeur=valeur,
            date_evaluation=jour,
            source=SOURCE_SAISIE,
            notes=note,
            created_at=datetime.now(timezone.utc),
        )
        db.add(cible)
    await db.flush()
    # Une seule évaluation de référence par immeuble.
    await db.execute(
        update(Evaluation)
        .where(Evaluation.immeuble_id == immeuble_id, Evaluation.id != cible.id)
        .values(is_reference=False)
    )
    cible.is_reference = True
    await db.flush()
    return cible
