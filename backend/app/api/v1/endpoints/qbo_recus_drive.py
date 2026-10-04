"""Reçus QuickBooks → Drive (chantier Phil 2026-10-04).

    GET  /api/v1/qbo-recus-drive/etat       état des entreprises + dernier run
    POST /api/v1/qbo-recus-drive/executer   lance un run (simulation ou réel)
    GET  /api/v1/qbo-recus-drive/journal    dernières copies

Le run tourne en arrière-plan ; ``/etat`` renvoie la progression puis le
rapport. Même service que la nuit (méga-cron all-daily).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DBSession
from app.services import qbo_recus_drive as svc

router = APIRouter(prefix="/qbo-recus-drive", tags=["qbo-recus-drive"])


class ExecuterIn(BaseModel):
    entreprise_ids: Optional[List[int]] = None
    depuis: Optional[date] = None
    jusqua: Optional[date] = None
    simulation: bool = Field(default=True)


@router.get("/etat", summary="Entreprises (QuickBooks + Drive) et dernier run")
async def etat(db: DBSession, _: CurrentUser) -> Dict[str, Any]:
    return {
        "entreprises": await svc.entreprises_etat(db),
        "run": svc.DERNIER_RUN,
        "mois": svc.MOIS_FR,
        "debut_par_defaut": svc.DEBUT_PAR_DEFAUT.isoformat(),
    }


@router.post("/executer", summary="Lance la copie (ou la simulation) des reçus")
async def executer(data: ExecuterIn, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    if svc.DERNIER_RUN.get("en_cours"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Un run est déjà en cours.")
    if data.depuis and data.jusqua and data.depuis > data.jusqua:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La date de début dépasse la date de fin.")
    svc.lancer_en_arriere_plan(
        entreprise_ids=data.entreprise_ids or None,
        depuis=data.depuis,
        jusqua=data.jusqua,
        simulation=data.simulation,
        declencheur="simulation" if data.simulation else "rattrapage",
        user_id=getattr(user, "id", None),
    )
    return {"lance": True, "simulation": data.simulation}


class ScopeIn(BaseModel):
    #: « construction » (QuickBooks d'Horizon) ou vide / « inc:{id} » (la sienne).
    scope: Optional[str] = None


@router.post(
    "/entreprises/{entreprise_id}/scope",
    summary="Choisit la connexion QuickBooks d'une entreprise (la sienne ou celle d'Horizon)",
)
async def changer_scope(
    entreprise_id: int, data: ScopeIn, db: DBSession, _: CurrentUser
) -> Dict[str, Any]:
    try:
        scope = await svc.changer_scope(db, entreprise_id, data.scope)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {"entreprise_id": entreprise_id, "qbo_scope": scope}


@router.get("/journal", summary="Dernières copies (mémoire anti-doublon)")
async def journal(
    db: DBSession,
    _: CurrentUser,
    entreprise_id: Optional[int] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> List[Dict[str, Any]]:
    return await svc.journal(db, entreprise_id=entreprise_id, limit=limit)
