"""Documents Drive d'un immeuble (Steven, 2026-11-13).

Voir ``app.services.immeuble_drive``. Réservé aux gestionnaires (manager
et plus) qui voient l'immeuble : on y trouve taxes, assurances, prêts et
actes. Lecture seule côté Drive ; la seule écriture est le lien
immeuble ↔ dossier (``DriveEntityLink`` « Immeuble »).

- ``GET  /immobilier/immeubles/{id}/drive`` : dossier relié + documents
  rangés par catégorie ; sans lien, les dossiers candidats (et
  ``suggestion`` quand l'un est certain).
- ``POST /immobilier/immeubles/{id}/drive/relier`` : ``{"dossier_id"}``
  pour un dossier choisi, ou ``{"auto": true}`` pour le candidat certain.
- ``POST /immobilier/immeubles-drive/relier-tous?simuler=true`` : repère
  et relie d'un coup tous les immeubles sans dossier (admin).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireAdminOrOwner
from app.core.permissions import visible_immeuble_ids
from app.models.immobilier import Immeuble
from app.services import immeuble_drive as svc
from app.services.audit import log_action
from app.services.drive_exceptions import DriveAuthError, DriveError, DriveNotFoundError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/immobilier", tags=["immobilier-drive"])


class RelierDossier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dossier_id: Optional[str] = None
    dossier_nom: Optional[str] = None
    auto: bool = False


def _erreur_drive(exc: DriveError) -> HTTPException:
    if isinstance(exc, DriveAuthError):
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {
                "message": "Google Drive n'est pas connecté dans Kratos.",
                "code": "drive_non_connecte",
                "ou": "Paramètres → Drive",
            },
        )
    if isinstance(exc, DriveNotFoundError):
        return HTTPException(
            status.HTTP_404_NOT_FOUND,
            {
                "message": "Le dossier Drive relié est introuvable (supprimé ou plus partagé).",
                "code": "dossier_introuvable",
            },
        )
    return HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        {"message": f"Google Drive ne répond pas : {exc}", "code": "drive_erreur"},
    )


async def _immeuble_ou_erreur(db, user, immeuble_id: int) -> Immeuble:
    volets = getattr(user, "volets", None) or []
    if "immobilier" not in volets:
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"message": "Volet « Immobilier » non autorisé."})
    if not user.has_min_role("manager"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "message": "Les documents Drive de l'immeuble sont réservés aux gestionnaires.",
                "code": "reserve_gestionnaires",
            },
        )
    imm = await db.get(Immeuble, immeuble_id)
    if imm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"message": f"Immeuble {immeuble_id} introuvable."})
    visibles = await visible_immeuble_ids(db, user)
    if visibles is not None and imm.id not in visibles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"message": "Accès à cet immeuble non autorisé."})
    return imm


@router.get("/immeubles/{immeuble_id}/drive")
async def documents_drive_immeuble(
    immeuble_id: int,
    db: DBSession,
    user: CurrentUser,
    rafraichir: bool = Query(False),
) -> dict[str, Any]:
    imm = await _immeuble_ou_erreur(db, user, immeuble_id)
    lien = await svc.lien_immeuble(db, imm.id)
    try:
        if lien is None:
            candidats, certain = await svc.trouver_dossiers_candidats(
                db, user.id, imm, rafraichir=rafraichir
            )
            await db.commit()
            return {
                "immeuble_id": imm.id,
                "dossier": None,
                "candidats": [c.as_dict() for c in candidats],
                "suggestion": certain.as_dict() if certain else None,
                "categories": [],
            }
        docs = await svc.documents_dossier(
            db, user.id, lien.drive_folder_id, rafraichir=rafraichir
        )
    except DriveError as exc:
        await db.rollback()
        raise _erreur_drive(exc) from exc
    await db.commit()
    return {
        "immeuble_id": imm.id,
        "dossier": {
            "id": lien.drive_folder_id,
            "nom": lien.drive_folder_name,
            "url": f"https://drive.google.com/drive/folders/{lien.drive_folder_id}",
            "lien_id": lien.id,
        },
        "candidats": [],
        "suggestion": None,
        **docs,
    }


@router.post("/immeubles/{immeuble_id}/drive/relier")
async def relier_dossier_drive(
    immeuble_id: int,
    db: DBSession,
    user: CurrentUser,
    payload: RelierDossier = Body(...),
) -> dict[str, Any]:
    imm = await _immeuble_ou_erreur(db, user, immeuble_id)
    dossier_id = (payload.dossier_id or "").strip() or None
    dossier_nom = payload.dossier_nom
    source = "choisi"
    if payload.auto:
        if await svc.lien_immeuble(db, imm.id) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"message": "Cet immeuble est déjà relié à un dossier Drive."},
            )
        try:
            _, certain = await svc.trouver_dossiers_candidats(db, user.id, imm)
        except DriveError as exc:
            raise _erreur_drive(exc) from exc
        if certain is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"message": "Aucun dossier Drive ne correspond avec certitude : choisis-le dans la liste."},
            )
        dossier_id, dossier_nom, source = certain.id, certain.nom, "auto"
    if not dossier_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": "dossier_id requis."})
    if source == "choisi" and not user.has_min_role("admin"):
        # Re-cibler à la main : admin / propriétaire, comme les liens Drive.
        existant = await svc.lien_immeuble(db, imm.id)
        if existant is not None or not user.has_min_role("manager"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                {"message": "Changer le dossier Drive d'un immeuble est réservé aux administrateurs."},
            )
    lien = await svc.relier(db, imm.id, dossier_id, dossier_nom, user.id)
    await log_action(
        db,
        user=user,
        action="immeuble.drive.relier",
        entity_type="immeuble",
        entity_id=imm.id,
        details={"drive_folder_id": dossier_id, "nom": dossier_nom, "source": source},
    )
    await db.commit()
    svc.oublier_cache(dossier_id)
    return {"lien_id": lien.id, "dossier_id": dossier_id, "dossier_nom": dossier_nom, "source": source}


@router.post("/immeubles-drive/relier-tous")
async def relier_tous_les_immeubles(
    db: DBSession,
    user: RequireAdminOrOwner,
    simuler: bool = Query(True),
) -> dict[str, Any]:
    """Repère le dossier de chaque immeuble actif sans lien, relie les certains."""
    immeubles = (
        await db.execute(select(Immeuble).where(Immeuble.is_active.is_(True)).order_by(Immeuble.id))
    ).scalars().all()
    resultats: list[dict[str, Any]] = []
    try:
        await svc.inventaire_dossiers(db, user.id, rafraichir=True)
        for imm in immeubles:
            lien = await svc.lien_immeuble(db, imm.id)
            if lien is not None:
                resultats.append(
                    {"immeuble_id": imm.id, "nom": imm.name, "etat": "deja_relie", "dossier_id": lien.drive_folder_id}
                )
                continue
            candidats, certain = await svc.trouver_dossiers_candidats(db, user.id, imm)
            ligne: dict[str, Any] = {
                "immeuble_id": imm.id,
                "nom": imm.name,
                "candidats": [c.as_dict() for c in candidats[:4]],
            }
            if certain is None:
                ligne["etat"] = "a_choisir" if candidats else "introuvable"
            else:
                ligne["etat"] = "simule" if simuler else "relie"
                ligne["dossier"] = certain.as_dict()
                if not simuler:
                    await svc.relier(db, imm.id, certain.id, certain.nom, user.id)
            resultats.append(ligne)
    except DriveError as exc:
        await db.rollback()
        raise _erreur_drive(exc) from exc
    if not simuler:
        await log_action(
            db,
            user=user,
            action="immeuble.drive.relier_tous",
            entity_type="immeuble",
            entity_id=None,
            details={"relies": [r["immeuble_id"] for r in resultats if r["etat"] == "relie"]},
        )
    await db.commit()
    return {"simuler": simuler, "immeubles": resultats}
