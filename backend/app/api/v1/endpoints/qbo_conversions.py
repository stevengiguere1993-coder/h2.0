"""Comptabilité → « Projets QB » (Steven, 2026-10-14).

Liste des sous-clients QuickBooks créés par Kratos qu'il reste à
convertir en PROJET dans QuickBooks (onglet Projets), ce que l'API
Intuit ne permet pas sans palier partenaire Silver. La conversion se
fait dans QuickBooks — par l'extension Chrome Horizon sur la page
Projets, ou à la main — et Kratos la CONSTATE par l'API (« Vérifier »,
passage de nuit). Voir ``services/qbo_projets_conversion``.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import DBSession
from app.models.project import Project
from app.services import qbo_projets_conversion as svc
from app.services.permissions_service import require_capability

router = APIRouter(
    prefix="/qbo-conversions",
    tags=["qbo-conversions"],
    dependencies=[Depends(require_capability("page:entreprises.comptabilite"))],
)


def _http(exc: svc.ConversionErreur) -> HTTPException:
    return HTTPException(exc.statut, exc.message)


@router.get("", summary="Sous-clients à convertir en projet QuickBooks")
async def lister(db: DBSession) -> Dict[str, Any]:
    return await svc.liste(db)


@router.post("/verifier", summary="Constater dans QuickBooks les conversions faites")
async def verifier(db: DBSession) -> Dict[str, Any]:
    try:
        return await svc.verifier(db)
    except svc.ConversionErreur as exc:
        raise _http(exc) from exc


@router.post(
    "/ajouter-existants",
    summary="Mettre dans la liste les projets d'avant (sous-client pas encore converti)",
)
async def ajouter_existants(db: DBSession) -> Dict[str, Any]:
    try:
        return await svc.ajouter_existants(db)
    except svc.ConversionErreur as exc:
        raise _http(exc) from exc


async def _projet(db: DBSession, project_id: int) -> Project:
    proj = await db.get(Project, project_id)
    if proj is None or proj.qbo_conversion_etat is None:
        raise HTTPException(404, "Projet introuvable dans la liste des conversions")
    return proj


@router.post("/{project_id}/ignorer", summary="Ne pas convertir ce sous-client")
async def ignorer(project_id: int, db: DBSession) -> Dict[str, Any]:
    proj = await _projet(db, project_id)
    svc.ignorer(proj)
    await db.flush()
    return {"ok": True, "project_id": proj.id, "etat": proj.qbo_conversion_etat}


@router.post("/{project_id}/reprendre", summary="Remettre ce sous-client dans la liste")
async def reprendre(project_id: int, db: DBSession) -> Dict[str, Any]:
    proj = await _projet(db, project_id)
    svc.reprendre(proj)
    await db.flush()
    return {"ok": True, "project_id": proj.id, "etat": proj.qbo_conversion_etat}
