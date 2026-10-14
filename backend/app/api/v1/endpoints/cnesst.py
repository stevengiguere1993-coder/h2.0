"""Prime CNESST — taux global (Paramètres → Prime CNESST).

Le taux global s'ajoute au coût horaire de tous les employés dont la case
« Prime CNESST » est cochée et qui n'ont pas de taux personnalisé sur leur
fiche. Il est DATÉ : un nouveau taux vaut à partir de sa date et les heures
punchées avant gardent l'ancien. Règle complète : ``app/services/cnesst.py``.

    GET    /api/v1/construction/cnesst                    barème, taux actuel, prime de chaque employé actif
    PUT    /api/v1/construction/cnesst                    nouveau taux à partir d'une date
    DELETE /api/v1/construction/cnesst/paliers/{depuis}   retire un palier (sauf le premier)

Taux en DÉCIMAL (0.0216 = 2,16 %), comme sur la fiche employé.
"""

from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.employe import Employe
from app.services.audit import log_action
from app.services.cnesst import (
    BaremeCnesst,
    charger_bareme_cnesst,
    enregistrer_bareme_cnesst,
    taux_cnesst,
)
from app.services.punch_diner import aujourd_hui_local

router = APIRouter(prefix="/construction/cnesst", tags=["cnesst"])


class PalierCnesstRead(BaseModel):
    depuis: date
    taux: float


class EmployeCnesstRead(BaseModel):
    id: int
    full_name: str
    cnesst_actif: bool
    #: Taux personnalisé ; None = suit le taux global.
    cnesst_rate: Optional[float]
    #: « global », « perso » ou « aucune » (case décochée).
    source: Literal["global", "perso", "aucune"]
    #: Prime appliquée aujourd'hui.
    taux_effectif: float


class CnesstRead(BaseModel):
    taux_actuel: float
    paliers: List[PalierCnesstRead]
    employes: List[EmployeCnesstRead]


class CnesstUpdate(BaseModel):
    taux: float = Field(..., ge=0, le=1)
    #: Date d'entrée en vigueur ; vide = aujourd'hui.
    depuis: Optional[date] = None


async def _etat(db, bareme: BaremeCnesst) -> CnesstRead:
    emps = (
        await db.execute(
            select(Employe)
            .where(Employe.active.is_(True))
            .order_by(Employe.full_name.asc())
        )
    ).scalars().all()
    employes: List[EmployeCnesstRead] = []
    for e in emps:
        actif = e.cnesst_actif is not False
        perso = float(e.cnesst_rate) if e.cnesst_rate is not None else None
        employes.append(
            EmployeCnesstRead(
                id=e.id,
                full_name=e.full_name,
                cnesst_actif=actif,
                cnesst_rate=perso,
                source=(
                    "aucune" if not actif else "perso" if perso is not None else "global"
                ),
                taux_effectif=taux_cnesst(actif, perso, bareme, None),
            )
        )
    return CnesstRead(
        taux_actuel=bareme.taux_actuel,
        paliers=[PalierCnesstRead(depuis=p.depuis, taux=p.taux) for p in bareme.paliers],
        employes=employes,
    )


@router.get(
    "",
    response_model=CnesstRead,
    summary="Taux CNESST global (barème daté) et prime de chaque employé actif",
)
async def lire_cnesst(db: DBSession, _: CurrentUser) -> CnesstRead:
    return await _etat(db, await charger_bareme_cnesst(db))


@router.put(
    "",
    response_model=CnesstRead,
    summary="Nouveau taux CNESST global à partir d'une date",
)
async def modifier_cnesst(
    data: CnesstUpdate, db: DBSession, user: RequireManager
) -> CnesstRead:
    """Le taux vaut à partir de ``depuis`` (aujourd'hui par défaut) ; un
    palier existant à cette date est remplacé. Les heures punchées avant
    gardent le taux d'alors."""
    depuis = data.depuis or aujourd_hui_local()
    bareme = await charger_bareme_cnesst(db)
    avant = bareme.taux_au(depuis) if bareme.paliers else None
    bareme = bareme.avec_palier(depuis, data.taux)
    await enregistrer_bareme_cnesst(db, bareme, user_id=user.id)
    await log_action(
        db,
        user=user,
        action="cnesst.taux_global",
        entity_type="cnesst",
        details={"depuis": depuis.isoformat(), "taux": data.taux, "avant": avant},
    )
    return await _etat(db, bareme)


@router.delete(
    "/paliers/{depuis}",
    response_model=CnesstRead,
    summary="Retire un palier du taux CNESST global",
)
async def supprimer_palier_cnesst(
    depuis: date, db: DBSession, user: RequireManager
) -> CnesstRead:
    bareme = await charger_bareme_cnesst(db)
    dates = [p.depuis for p in bareme.paliers]
    if depuis not in dates:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Palier introuvable.")
    if depuis == dates[0]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Le premier taux couvre tout le passé : il ne se supprime pas. "
            "Ajoute plutôt un nouveau taux à partir d'une date.",
        )
    taux = bareme.taux_au(depuis)
    bareme = bareme.sans_palier(depuis)
    await enregistrer_bareme_cnesst(db, bareme, user_id=user.id)
    await log_action(
        db,
        user=user,
        action="cnesst.palier_supprime",
        entity_type="cnesst",
        details={"depuis": depuis.isoformat(), "taux": taux},
    )
    return await _etat(db, bareme)
