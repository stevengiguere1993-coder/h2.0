"""Endpoints achats (depenses) d'un projet Dev Logiciel.

    GET    /api/v1/devlog/projects/{project_id}/purchases
    POST   /api/v1/devlog/projects/{project_id}/purchases
    PATCH  /api/v1/devlog/projects/{project_id}/purchases/{id}
    DELETE /api/v1/devlog/projects/{project_id}/purchases/{id}
    POST   /api/v1/devlog/projects/{project_id}/purchases/{id}/receipt
    GET    /api/v1/devlog/projects/{project_id}/purchases/{id}/receipt

Tous proteges par le guard admin/owner du pole et loguent les
mutations dans audit_logs.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.devlog_project import DevlogProject
from app.models.devlog_project_purchase import DevlogProjectPurchase
from app.schemas.devlog import (
    DevlogProjectPurchaseCreate,
    DevlogProjectPurchaseRead,
    DevlogProjectPurchaseUpdate,
)
from app.services.audit import log_action


router = APIRouter(
    prefix="/devlog/projects", tags=["devlog-project-purchases"]
)


_ALLOWED_RECEIPT_CT = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "image/gif",
    "application/pdf",
}
_MAX_RECEIPT_BYTES = 15 * 1024 * 1024  # 15 Mo


async def _get_project_or_404(db, project_id: int) -> DevlogProject:
    obj = (
        await db.execute(
            select(DevlogProject).where(DevlogProject.id == project_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable")
    return obj


async def _get_purchase_or_404(
    db, project_id: int, purchase_id: int
) -> DevlogProjectPurchase:
    obj = (
        await db.execute(
            select(DevlogProjectPurchase).where(
                DevlogProjectPurchase.id == purchase_id,
                DevlogProjectPurchase.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achat introuvable")
    return obj


def _to_read(obj: DevlogProjectPurchase) -> DevlogProjectPurchaseRead:
    return DevlogProjectPurchaseRead(
        id=obj.id,
        project_id=obj.project_id,
        description=obj.description,
        amount_cents=obj.amount_cents,
        supplier=obj.supplier,
        purchased_at=obj.purchased_at,
        notes=obj.notes,
        has_receipt=bool(obj.receipt_filename),
        receipt_filename=obj.receipt_filename,
        receipt_content_type=obj.receipt_content_type,
        created_by_user_id=obj.created_by_user_id,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


@router.get(
    "/{project_id}/purchases",
    response_model=List[DevlogProjectPurchaseRead],
)
async def list_purchases(
    project_id: int, db: DBSession, _: CurrentUser
) -> List[DevlogProjectPurchaseRead]:
    await _get_project_or_404(db, project_id)
    rows = (
        await db.execute(
            select(DevlogProjectPurchase)
            .where(DevlogProjectPurchase.project_id == project_id)
            .order_by(
                DevlogProjectPurchase.purchased_at.desc().nullslast(),
                DevlogProjectPurchase.id.desc(),
            )
        )
    ).scalars().all()
    return [_to_read(r) for r in rows]


@router.post(
    "/{project_id}/purchases",
    response_model=DevlogProjectPurchaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_purchase(
    project_id: int,
    data: DevlogProjectPurchaseCreate,
    db: DBSession,
    user: CurrentUser,
) -> DevlogProjectPurchaseRead:
    await _get_project_or_404(db, project_id)
    obj = DevlogProjectPurchase(
        project_id=project_id,
        description=data.description.strip(),
        amount_cents=int(data.amount_cents),
        supplier=(data.supplier.strip() if data.supplier else None),
        purchased_at=data.purchased_at,
        notes=(data.notes.strip() if data.notes else None),
        created_by_user_id=user.id,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await log_action(
        db,
        user=user,
        action="devlog_project_purchase.created",
        entity_type="devlog_project_purchase",
        entity_id=obj.id,
        details={
            "project_id": project_id,
            "amount_cents": obj.amount_cents,
            "description": obj.description,
        },
    )
    return _to_read(obj)


@router.patch(
    "/{project_id}/purchases/{purchase_id}",
    response_model=DevlogProjectPurchaseRead,
)
async def update_purchase(
    project_id: int,
    purchase_id: int,
    data: DevlogProjectPurchaseUpdate,
    db: DBSession,
    user: CurrentUser,
) -> DevlogProjectPurchaseRead:
    obj = await _get_purchase_or_404(db, project_id, purchase_id)
    fields = data.model_dump(exclude_unset=True)
    if "description" in fields and isinstance(fields["description"], str):
        fields["description"] = fields["description"].strip()
    if "supplier" in fields and isinstance(fields["supplier"], str):
        fields["supplier"] = fields["supplier"].strip() or None
    if "notes" in fields and isinstance(fields["notes"], str):
        fields["notes"] = fields["notes"].strip() or None
    for k, v in fields.items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    await log_action(
        db,
        user=user,
        action="devlog_project_purchase.updated",
        entity_type="devlog_project_purchase",
        entity_id=obj.id,
        details={"project_id": project_id, **fields},
    )
    return _to_read(obj)


@router.delete(
    "/{project_id}/purchases/{purchase_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_purchase(
    project_id: int,
    purchase_id: int,
    db: DBSession,
    user: CurrentUser,
) -> Response:
    obj = await _get_purchase_or_404(db, project_id, purchase_id)
    await db.delete(obj)
    await db.flush()
    await log_action(
        db,
        user=user,
        action="devlog_project_purchase.deleted",
        entity_type="devlog_project_purchase",
        entity_id=purchase_id,
        details={"project_id": project_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/purchases/{purchase_id}/receipt",
    response_model=DevlogProjectPurchaseRead,
)
async def upload_receipt(
    project_id: int,
    purchase_id: int,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> DevlogProjectPurchaseRead:
    obj = await _get_purchase_or_404(db, project_id, purchase_id)
    ct = (file.content_type or "").lower()
    if ct not in _ALLOWED_RECEIPT_CT:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Format de recu non supporte (JPG/PNG/WEBP/HEIC/PDF).",
        )
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")
    if len(blob) > _MAX_RECEIPT_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Recu trop gros (> {_MAX_RECEIPT_BYTES // (1024 * 1024)} Mo).",
        )
    obj.receipt_blob = blob
    obj.receipt_filename = file.filename or f"receipt-{obj.id}"
    obj.receipt_content_type = ct
    await db.flush()
    await db.refresh(obj)
    await log_action(
        db,
        user=user,
        action="devlog_project_purchase.receipt_uploaded",
        entity_type="devlog_project_purchase",
        entity_id=obj.id,
        details={
            "project_id": project_id,
            "filename": obj.receipt_filename,
            "size_bytes": len(blob),
        },
    )
    return _to_read(obj)


@router.get("/{project_id}/purchases/{purchase_id}/receipt")
async def get_receipt(
    project_id: int,
    purchase_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    obj = await _get_purchase_or_404(db, project_id, purchase_id)
    await db.refresh(obj, attribute_names=["receipt_blob"])
    if not obj.receipt_blob or not obj.receipt_content_type:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucun recu.")
    filename = obj.receipt_filename or f"receipt-{obj.id}"
    return Response(
        content=bytes(obj.receipt_blob),
        media_type=obj.receipt_content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
