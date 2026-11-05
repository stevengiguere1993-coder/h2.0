"""Comptabilité → « Clients en double » (Steven, 2026-10-18).

Doublons de clients dans chaque compagnie QuickBooks connectée (Horizon,
autres pôles, INC). Intuit ne fusionne pas de clients par API : la fusion
se fait dans QuickBooks en renommant le doublon au nom exact de la fiche
gardée, et Kratos suit (liens, noms). Une fiche vide est désactivée par
l'API. Voir ``services/qbo_doublons``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import DBSession
from app.services import qbo_doublons as svc
from app.services.permissions_service import require_capability

router = APIRouter(
    prefix="/qbo-doublons",
    tags=["qbo-doublons"],
    dependencies=[Depends(require_capability("page:entreprises.comptabilite"))],
)


def _http(exc: svc.DoublonErreur) -> HTTPException:
    return HTTPException(exc.statut, exc.message)


class PaireIn(BaseModel):
    """Une fiche à faire disparaître (``source_id``) au profit de celle à
    garder (``cible_id``), dans la compagnie ``scope``."""

    scope: str = Field(..., max_length=32)
    source_id: str = Field(..., min_length=1, max_length=64)
    cible_id: str = Field(..., min_length=1, max_length=64)
    #: Nom exact du doublon tel qu'affiché à l'analyse : QuickBooks le
    #: change (« (deleted) ») quand la fiche disparaît.
    nom_source: Optional[str] = Field(default=None, max_length=255)


@router.get("", summary="Compagnies QuickBooks connectées et entreprises non connectées")
async def lister_compagnies(db: DBSession) -> Dict[str, Any]:
    return await svc.compagnies(db)


@router.get("/analyse", summary="Doublons de clients d'une compagnie QuickBooks")
async def analyser(db: DBSession, scope: str = Query(..., max_length=32)) -> Dict[str, Any]:
    try:
        return await svc.analyser(db, scope)
    except svc.DoublonErreur as exc:
        raise _http(exc) from exc


@router.get("/paire", summary="Deux clients choisis à la main, présentés comme un groupe")
async def paire(
    db: DBSession,
    scope: str = Query(..., max_length=32),
    ids: str = Query(..., max_length=200, description="Ids QuickBooks séparés par des virgules"),
) -> Dict[str, Any]:
    try:
        return await svc.groupe_choisi(db, scope, ids.split(","))
    except svc.DoublonErreur as exc:
        raise _http(exc) from exc


@router.get("/apercu", summary="Ce que porte un client (ventes, paiements, sous-clients)")
async def apercu(
    db: DBSession,
    scope: str = Query(..., max_length=32),
    id: str = Query(..., min_length=1, max_length=64),  # noqa: A002
) -> Dict[str, Any]:
    try:
        return await svc.apercu(db, scope, id)
    except svc.DoublonErreur as exc:
        raise _http(exc) from exc


@router.post("/fusion", summary="Fusion faite dans QuickBooks : Kratos suit sur la fiche gardée")
async def fusion_faite(body: PaireIn, db: DBSession) -> Dict[str, Any]:
    try:
        return await svc.fusion_faite(
            db,
            body.scope,
            source_id=body.source_id.strip(),
            cible_id=body.cible_id.strip(),
            nom_source=body.nom_source,
        )
    except svc.DoublonErreur as exc:
        raise _http(exc) from exc


@router.post("/desactiver", summary="Désactiver par l'API un doublon vide, puis suivre")
async def desactiver(body: PaireIn, db: DBSession) -> Dict[str, Any]:
    try:
        return await svc.desactiver(
            db,
            body.scope,
            source_id=body.source_id.strip(),
            cible_id=body.cible_id.strip(),
            nom_source=body.nom_source,
        )
    except svc.DoublonErreur as exc:
        raise _http(exc) from exc


@router.post(
    "/clients-kratos/{client_id}/nom-quickbooks",
    summary="La fiche client Kratos prend le nom exact de son client QuickBooks",
)
async def nom_quickbooks(client_id: int, db: DBSession) -> Dict[str, Any]:
    try:
        return await svc.aligner_nom_kratos(db, client_id)
    except svc.DoublonErreur as exc:
        raise _http(exc) from exc
