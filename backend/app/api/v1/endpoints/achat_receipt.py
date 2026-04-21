"""Upload / download / delete the scanned receipt image attached to
an Achat (purchase order)."""

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.achat import Achat


router = APIRouter(prefix="/achats", tags=["achat-receipt"])


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

    ac.receipt_image = blob
    ac.receipt_image_content_type = ct
    await db.flush()
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


@router.delete(
    "/{achat_id}/receipt",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove the receipt image from an achat",
)
async def delete_receipt(
    achat_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    ac = (
        await db.execute(select(Achat).where(Achat.id == achat_id))
    ).scalar_one_or_none()
    if ac is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achat not found")
    ac.receipt_image = None
    ac.receipt_image_content_type = None
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
