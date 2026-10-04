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
    #: Mode « ce qui a bougé dans QuickBooks depuis N jours » (comme la
    #: nuit) : ignore la période, prend toute pièce ajoutée/modifiée.
    pieces_depuis_jours: Optional[int] = Field(default=None, ge=1, le=365)


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
        depuis=None if data.pieces_depuis_jours else data.depuis,
        jusqua=None if data.pieces_depuis_jours else data.jusqua,
        simulation=data.simulation,
        declencheur="simulation" if data.simulation else "rattrapage",
        user_id=getattr(user, "id", None),
        pieces_depuis_jours=data.pieces_depuis_jours,
    )
    return {"lance": True, "simulation": data.simulation}


@router.post("/arreter", summary="Arrête le run en cours (ce qui est copié reste copié)")
async def arreter(_: CurrentUser) -> Dict[str, Any]:
    return {"arret_demande": svc.demander_arret()}


@router.get("/runs", summary="Imports réels récents (pour annulation)")
async def runs(db: DBSession, _: CurrentUser) -> List[Dict[str, Any]]:
    return await svc.runs_recents(db)


@router.post(
    "/annuler/{run_id}",
    summary="Annule un import : fichiers copiés à la corbeille Drive, mémoire effacée",
)
async def annuler(run_id: str, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    r = await svc.annuler_run(db, run_id, user_id=getattr(user, "id", None))
    if not r.get("ok"):
        raise HTTPException(status.HTTP_409_CONFLICT, r.get("erreur") or "Annulation impossible.")
    return r


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


@router.get(
    "/entreprises/{entreprise_id}/dossier-factures",
    summary="Dossier Drive de l'entreprise et son sous-dossier Factures (lecture seule)",
)
async def dossier_factures(entreprise_id: int, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    try:
        return await svc.dossier_factures(db, entreprise_id, user_id=getattr(user, "id", None))
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/journal", summary="Dernières copies (mémoire anti-doublon)")
async def journal(
    db: DBSession,
    _: CurrentUser,
    entreprise_id: Optional[int] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> List[Dict[str, Any]]:
    return await svc.journal(db, entreprise_id=entreprise_id, limit=limit)
