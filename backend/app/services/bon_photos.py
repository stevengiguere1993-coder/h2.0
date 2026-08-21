"""Photos d'un bon de travail — logique PARTAGÉE (2026-08-21).

Avant : l'upload et la lecture vivaient uniquement dans le routeur
IMMOBILIER (``/immobilier/bons-travail/{id}/photos``), gardés par le
volet immobilier et réservés aux bons « gestion immo ». La page des bons
du pôle CONSTRUCTION appelait pourtant ces mêmes routes : un chargé de
projet sans volet immobilier recevait un 403, et l'écran l'avalait —
« je ne suis pas capable de mettre de photo dans mes bons ».

Deux routeurs exposent désormais la MÊME logique, chacun avec sa garde :
- ``/bons-travail/{id}/photos`` (construction OU immobilier, tout bon) ;
- ``/immobilier/bons-travail/{id}/photos`` (volet immobilier, bons
  gestion immo — la porte « Kyle »), inchangé pour ses appelants.

Les photos sont portées par le PROJET lié au bon (mini-projet créé au
besoin) : c'est déjà ainsi que les bons internes fonctionnent, et ça
garde une seule source pour les photos de chantier.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bon_travail import BonTravail
from app.models.project import Project
from app.models.project_photo import ProjectPhoto

PHOTO_MIME_ALLOWED = {
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
}
PHOTO_MAX_BYTES = 8 * 1024 * 1024  # 8 Mo


class PhotoBonError(ValueError):
    """Erreur métier à traduire en HTTP par l'appelant (status, detail)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


async def lister_photos_bon(
    db: AsyncSession, bon: BonTravail
) -> Sequence[Any]:
    """Métadonnées des photos du bon (sans charger les octets)."""
    if bon.project_id is None:
        return []
    return (
        await db.execute(
            select(
                ProjectPhoto.id,
                ProjectPhoto.caption,
                ProjectPhoto.content_type,
                ProjectPhoto.created_at,
            )
            .where(ProjectPhoto.project_id == bon.project_id)
            .order_by(ProjectPhoto.created_at.desc(), ProjectPhoto.id.desc())
        )
    ).all()


async def charger_photo_bon(
    db: AsyncSession, bon: BonTravail, photo_id: int
) -> Optional[tuple[bytes, str]]:
    """Octets + type MIME d'une photo, en vérifiant qu'elle appartient
    bien au chantier de CE bon (pas d'accès par id deviné)."""
    if bon.project_id is None:
        return None
    row = (
        await db.execute(
            select(ProjectPhoto.image, ProjectPhoto.content_type).where(
                ProjectPhoto.id == photo_id,
                ProjectPhoto.project_id == bon.project_id,
            )
        )
    ).first()
    if row is None or not row[0]:
        return None
    return bytes(row[0]), (row[1] or "image/jpeg")


async def enregistrer_photo_bon(
    db: AsyncSession,
    bon: BonTravail,
    *,
    content_type: Optional[str],
    blob: bytes,
    uploaded_by_email: Optional[str],
    caption: str = "Problématique (avant)",
) -> ProjectPhoto:
    """Valide et enregistre une photo (ou un PDF) sur le bon.

    Crée le mini-projet porteur si le bon n'en a pas encore. N'appelle
    PAS ``commit`` : la transaction reste à l'appelant.
    """
    ct = (content_type or "").lower()
    if ct not in PHOTO_MIME_ALLOWED and ct != "application/pdf":
        raise PhotoBonError(
            415, "Format non supporté (JPG, PNG, WEBP, HEIC, PDF)."
        )
    if not blob:
        raise PhotoBonError(400, "Fichier vide.")
    if len(blob) > PHOTO_MAX_BYTES:
        raise PhotoBonError(
            413,
            f"Fichier trop gros (> {PHOTO_MAX_BYTES // (1024 * 1024)} Mo).",
        )

    if bon.project_id is None:
        proj = Project(
            name=bon.title or f"Bon {bon.reference}",
            client_id=bon.client_id,
            kind="bon_travail",
            responsible_user_id=getattr(bon, "assignee_user_id", None),
            status="in_progress",
            address=getattr(bon, "address", None),
        )
        db.add(proj)
        await db.flush()
        bon.project_id = proj.id

    photo = ProjectPhoto(
        project_id=bon.project_id,
        image=blob,
        content_type=ct,
        caption=caption,
        uploaded_by_email=uploaded_by_email,
    )
    db.add(photo)
    await db.flush()
    return photo


async def supprimer_photo_bon(
    db: AsyncSession, bon: BonTravail, photo_id: int
) -> bool:
    """Retire une photo du chantier de CE bon. False si elle n'y est pas."""
    if bon.project_id is None:
        return False
    photo = (
        await db.execute(
            select(ProjectPhoto).where(
                ProjectPhoto.id == photo_id,
                ProjectPhoto.project_id == bon.project_id,
            )
        )
    ).scalars().first()
    if photo is None:
        return False
    await db.delete(photo)
    await db.flush()
    return True
