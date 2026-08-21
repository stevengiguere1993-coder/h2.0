"""Photos d'un bon de travail — routeur GÉNÉRIQUE (construction OU immobilier).

    GET    /bons-travail/{bon_id}/photos              → métadonnées
    POST   /bons-travail/{bon_id}/photos              → upload (image/PDF)
    GET    /bons-travail/{bon_id}/photos/{photo_id}   → octets
    DELETE /bons-travail/{bon_id}/photos/{photo_id}

Monté avec ``DEP_CONSTRUCTION_IMMO`` — la même porte que le reste du bon
(items, envoi). Avant le 2026-08-21, seules des routes IMMOBILIER
existaient, gardées par le volet immobilier et réservées aux bons
« gestion immo » : un chargé de projet construction ne pouvait pas
joindre une photo, et l'écran avalait le refus.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.models.bon_travail import BonTravail
from app.services.bon_photos import (
    PhotoBonError,
    charger_photo_bon,
    enregistrer_photo_bon,
    lister_photos_bon,
    supprimer_photo_bon,
)

router = APIRouter(prefix="/bons-travail", tags=["bon-photos"])


class BonPhotoMeta(BaseModel):
    id: int
    caption: Optional[str] = None
    content_type: str
    created_at: Optional[datetime] = None


async def _bon_or_404(db, bon_id: int) -> BonTravail:
    bon = await db.get(BonTravail, bon_id)
    if bon is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bon introuvable."
        )
    return bon


@router.get("/{bon_id}/photos", response_model=List[BonPhotoMeta])
async def list_bon_photos(
    bon_id: int, db: DBSession, user: CurrentUser
) -> List[BonPhotoMeta]:
    bon = await _bon_or_404(db, bon_id)
    rows = await lister_photos_bon(db, bon)
    return [
        BonPhotoMeta(id=pid, caption=cap, content_type=ct, created_at=ca)
        for pid, cap, ct, ca in rows
    ]


@router.post("/{bon_id}/photos", status_code=status.HTTP_201_CREATED)
async def upload_bon_photo(
    bon_id: int,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> dict:
    """Ajoute une photo (avant / après) ou un PDF au bon — quel que soit
    son type (interne, construction, gestion immo)."""
    bon = await _bon_or_404(db, bon_id)
    blob = await file.read()
    try:
        photo = await enregistrer_photo_bon(
            db,
            bon,
            content_type=file.content_type,
            blob=blob,
            uploaded_by_email=getattr(user, "email", None),
        )
    except PhotoBonError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)
    await db.commit()
    return {"photo_id": photo.id, "project_id": bon.project_id}


@router.get("/{bon_id}/photos/{photo_id}")
async def get_bon_photo(
    bon_id: int, photo_id: int, db: DBSession, user: CurrentUser
) -> Response:
    bon = await _bon_or_404(db, bon_id)
    res = await charger_photo_bon(db, bon, photo_id)
    if res is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo introuvable."
        )
    content, ct = res
    return Response(content=content, media_type=ct)


@router.delete(
    "/{bon_id}/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_bon_photo(
    bon_id: int, photo_id: int, db: DBSession, user: CurrentUser
) -> None:
    bon = await _bon_or_404(db, bon_id)
    if not await supprimer_photo_bon(db, bon, photo_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo introuvable."
        )
    await db.commit()
