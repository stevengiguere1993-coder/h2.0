"""Liaison QuickBooks d'un PROJET de construction (sous-client sous le
client mère).

    POST /api/v1/projects/{id}/qbo/sync — crée / vérifie le sous-client
    QB du projet et retourne un compte rendu EXPLICITE (ou le motif exact
    de l'échec, aussi persisté sur ``Project.qbo_sync_error``).

Retour 2026-09-21 : le projet 1616 Saint-Alexandre (Jean-François
Croteau) n'apparaissait pas dans QuickBooks et rien ne disait pourquoi —
la création était une tâche de fond silencieuse. Cette action synchrone
donne à l'utilisateur le résultat sous les yeux.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.project import Project
from app.services.bon_project import (
    ProjectQboJobError,
    ensure_project_qbo_job,
    record_project_qbo_error,
)
from app.services.permissions_service import user_has_capability

router = APIRouter(prefix="/projects", tags=["project-qbo"])


class ProjectQboSyncResult(BaseModel):
    qbo_job_id: str
    parent_customer_id: str
    parent_name: str
    #: Nom complet QB du sous-client (« Client:Projet »).
    job_name: str
    #: deja_lie | adopte | cree
    action: str
    #: Projet Kratos qui portait ce sous-client à tort (lien transféré).
    transfere_de: Optional[int] = None
    message: Optional[str] = None


@router.post(
    "/{project_id}/qbo/sync",
    response_model=ProjectQboSyncResult,
    summary="Créer / vérifier le sous-client QuickBooks du projet",
)
async def sync_project_qbo(
    project_id: int, db: DBSession, user: CurrentUser
) -> ProjectQboSyncResult:
    if not await user_has_capability(db, user, "qbo.push"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes pour cette action.",
        )
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable.")
    try:
        res = await ensure_project_qbo_job(db, project)
    except ProjectQboJobError as exc:
        await db.rollback()
        await record_project_qbo_error(project_id, str(exc))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        msg = f"QuickBooks a répondu une erreur : {exc}"
        await record_project_qbo_error(project_id, msg)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=msg)
    project.qbo_sync_error = None
    await db.commit()
    libelle = {
        "deja_lie": "Le projet était déjà lié à ce sous-client QuickBooks.",
        "adopte": "Sous-client QuickBooks existant retrouvé et relié.",
        "cree": "Sous-client QuickBooks créé sous le client mère.",
    }.get(res["action"], "Projet lié à QuickBooks.")
    if res.get("transfere_de"):
        libelle += (
            f" Ce sous-client était relié à tort au projet "
            f"#{res['transfere_de']} — lien transféré."
        )
    return ProjectQboSyncResult(message=libelle, **res)
