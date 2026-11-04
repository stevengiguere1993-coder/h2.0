"""Upload / download / delete the scanned receipt image attached to
an Achat (purchase order).

Le reçu suit l'achat dans QuickBooks (Steven 2026-11-04 : « le PDF
devrait toujours se joindre dans les pièces jointes quand ça part de
Kratos et qu'il est présent ») : chaque arrivée, remplacement, rotation
ou retrait du reçu est répercuté sur la transaction QB en tâche de fond
(services/achat_piece_qbo.py), après l'enregistrement en base."""

from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.achat import Achat


router = APIRouter(prefix="/achats", tags=["achat-receipt"])


async def _soeurs(db, ac: Achat) -> list[Achat]:
    """Autres parts d'un reçu DIVISÉ entre plusieurs projets : la même
    facture vaut pour chacune → upload, rotation et suppression du reçu
    s'appliquent à tout le groupe. Vide pour un achat simple."""
    if not ac.groupe_id:
        return []
    from app.services.achat_divise import parts_du_groupe

    return [
        s
        for s in await parts_du_groupe(db, ac, actives_seulement=False)
        if s.id != ac.id
    ]


def _piece_qb_a_refaire(achats: list[Achat]) -> Optional[str]:
    """Le reçu change : la pièce QB connue ne vaut plus. Retourne son Id
    (à retirer de QB une fois la nouvelle version envoyée) et efface le
    lien sur toutes les parts."""
    ancien = next(
        (str(a.qbo_attachable_id) for a in achats if a.qbo_attachable_id),
        None,
    )
    for a in achats:
        a.qbo_attachable_id = None
    return ancien


def _joindre_a_qb_en_fond(
    taches: BackgroundTasks, achat_id: int, *, ancien: Optional[str]
) -> None:
    """Après la réponse (donc après le commit) : le reçu part vers la
    transaction QB de l'achat. Un remplacement (ancienne pièce connue)
    téléverse la nouvelle version puis retire l'ancienne."""
    from app.services.achat_piece_qbo import joindre_recu_en_fond

    taches.add_task(
        joindre_recu_en_fond,
        int(achat_id),
        retirer=ancien,
        forcer=bool(ancien),
    )


_ALLOWED_CONTENT = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "application/pdf",
}
_MAX_BYTES = 15 * 1024 * 1024  # 15 MB


@router.post(
    "/{achat_id}/receipt",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Upload or replace the receipt image for an achat",
)
async def upload_receipt(
    achat_id: int,
    db: DBSession,
    _: CurrentUser,
    taches: BackgroundTasks,
    file: UploadFile = File(...),
) -> Response:
    ac = (
        await db.execute(select(Achat).where(Achat.id == achat_id))
    ).scalar_one_or_none()
    if ac is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achat not found")

    ct = (file.content_type or "").lower()
    if ct not in _ALLOWED_CONTENT:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                "Format non supporté. Accepte JPG / PNG / WEBP / HEIC / PDF."
            ),
        )

    blob = await file.read()
    if len(blob) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")
    if len(blob) > _MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Fichier trop gros (>{_MAX_BYTES // (1024 * 1024)} Mo).",
        )

    soeurs = await _soeurs(db, ac)
    ac.receipt_image = blob
    ac.receipt_image_content_type = ct
    for s in soeurs:
        s.receipt_image = blob
        s.receipt_image_content_type = ct
    ancien = _piece_qb_a_refaire([ac, *soeurs])
    # Commit ICI (pas en fin de requête) : la tâche de fond relit l'achat
    # dans sa propre session et doit voir le reçu.
    await db.commit()
    _joindre_a_qb_en_fond(taches, achat_id, ancien=ancien)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{achat_id}/receipt",
    summary="Download / inline the receipt image of an achat",
)
async def download_receipt(
    achat_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    ac = (
        await db.execute(select(Achat).where(Achat.id == achat_id))
    ).scalar_one_or_none()
    if ac is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achat not found")
    # Force-load the deferred column for this single row.
    await db.refresh(ac, attribute_names=["receipt_image"])
    if not ac.receipt_image:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Aucune facture attachée à cet achat."
        )
    ct = ac.receipt_image_content_type or "application/octet-stream"
    # Inline display; for PDF the browser previews directly.
    ext = "pdf" if ct == "application/pdf" else ct.split("/")[-1]
    filename = f"recu-{ac.reference}.{ext}"
    return Response(
        content=bytes(ac.receipt_image),
        media_type=ct,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post(
    "/{achat_id}/receipt/rotate",
    summary="Pivoter la facture/reçu attaché de 90° (gauche ou droite)",
)
async def rotate_receipt(
    achat_id: int,
    db: DBSession,
    _: CurrentUser,
    taches: BackgroundTasks,
    direction: str = Query(
        default="left",
        pattern="^(left|right)$",
        description="Sens de rotation : 'left' (anti-horaire) ou 'right'.",
    ),
) -> dict:
    """Fait pivoter de 90° le PDF/image stocké, et le réenregistre.
    Permet de corriger un reçu mal orienté directement depuis la fiche.
    La version pivotée remplace la pièce dans QuickBooks."""
    ac = (
        await db.execute(select(Achat).where(Achat.id == achat_id))
    ).scalar_one_or_none()
    if ac is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achat not found")
    await db.refresh(ac, attribute_names=["receipt_image"])
    if not ac.receipt_image:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Aucune facture attachée à cet achat."
        )

    from app.services.receipt_rotate import rotate_receipt_blob

    rotated = rotate_receipt_blob(
        bytes(ac.receipt_image),
        ac.receipt_image_content_type or "",
        clockwise=(direction == "right"),
    )
    if rotated is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Rotation impossible pour ce format de fichier.",
        )
    soeurs = await _soeurs(db, ac)
    ac.receipt_image = rotated
    for s in soeurs:
        s.receipt_image = rotated
        s.receipt_image_content_type = ac.receipt_image_content_type
    ancien = _piece_qb_a_refaire([ac, *soeurs])
    await db.commit()
    _joindre_a_qb_en_fond(taches, achat_id, ancien=ancien)
    return {"rotated": True, "direction": direction}


@router.delete(
    "/{achat_id}/receipt",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove the receipt image from an achat",
)
async def delete_receipt(
    achat_id: int,
    db: DBSession,
    _: CurrentUser,
    taches: BackgroundTasks,
) -> Response:
    ac = (
        await db.execute(select(Achat).where(Achat.id == achat_id))
    ).scalar_one_or_none()
    if ac is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achat not found")
    soeurs = await _soeurs(db, ac)
    ac.receipt_image = None
    ac.receipt_image_content_type = None
    for s in soeurs:
        s.receipt_image = None
        s.receipt_image_content_type = None
    ancien = _piece_qb_a_refaire([ac, *soeurs])
    await db.commit()
    if ancien:
        # Le reçu quitte Kratos → sa pièce quitte aussi la transaction QB.
        from app.services.achat_piece_qbo import retirer_piece_qb_en_fond

        taches.add_task(retirer_piece_qb_en_fond, ancien)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
