"""Codes d'accès d'un immeuble — porte d'entrée, lock box, garage, alarme,
boîte aux lettres, Wi-Fi… (bug mvilliard 2026-10-17 sur la fiche
/immobilier/immeubles/19 : « ajouter un endroit pour code de porte, code
lock box et autre code relié à l'immeuble »).

Une liste de codes par immeuble (libellé, code, note facultative),
modifiable depuis la fiche et visible par quiconque voit l'immeuble
(mêmes règles de visibilité que la fiche : employé affecté ou manager+).
Les écritures sont journalisées par le middleware d'audit ; la lecture
IA passe par ``kratos_list_entities(immeuble_codes)``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.core.permissions import visible_immeuble_ids
from app.models.immobilier import Immeuble, ImmeubleCode
from app.schemas.immobilier import (
    ImmeubleCodeCreate,
    ImmeubleCodeRead,
    ImmeubleCodeUpdate,
)

router = APIRouter(prefix="/immobilier", tags=["immobilier-codes"])


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Immobilier » non autorisé pour cet utilisateur.",
        )


async def _immeuble_visible_ou_404(db, user, immeuble_id: int) -> Immeuble:
    """L'immeuble existe ET l'utilisateur le voit (employé affecté ou
    manager+) — un code de porte ne se devine pas par énumération."""
    imm = await db.get(Immeuble, immeuble_id)
    if imm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Immeuble {immeuble_id} introuvable.",
        )
    visibles = await visible_immeuble_ids(db, user)
    if visibles is not None and imm.id not in visibles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès à cet immeuble non autorisé.",
        )
    return imm


async def _code_ou_404(db, immeuble_id: int, code_id: int) -> ImmeubleCode:
    obj = await db.get(ImmeubleCode, code_id)
    if obj is None or obj.immeuble_id != immeuble_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Code introuvable pour cet immeuble.",
        )
    return obj


async def _liste(db, immeuble_id: int) -> List[ImmeubleCodeRead]:
    rows = (
        await db.execute(
            select(ImmeubleCode)
            .where(ImmeubleCode.immeuble_id == immeuble_id)
            .order_by(ImmeubleCode.position.asc(), ImmeubleCode.id.asc())
        )
    ).scalars().all()
    return [ImmeubleCodeRead.model_validate(r) for r in rows]


@router.get(
    "/immeubles/{immeuble_id}/codes",
    response_model=List[ImmeubleCodeRead],
    summary="Codes d'accès de l'immeuble (porte, lock box, garage…)",
)
async def list_codes_immeuble(
    immeuble_id: int, db: DBSession, user: CurrentUser
) -> List[ImmeubleCodeRead]:
    _require_volet(user)
    await _immeuble_visible_ou_404(db, user, immeuble_id)
    return await _liste(db, immeuble_id)


@router.post(
    "/immeubles/{immeuble_id}/codes",
    response_model=ImmeubleCodeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ajoute un code d'accès à l'immeuble",
)
async def create_code_immeuble(
    immeuble_id: int,
    payload: ImmeubleCodeCreate,
    db: DBSession,
    user: CurrentUser,
) -> ImmeubleCodeRead:
    _require_volet(user)
    await _immeuble_visible_ou_404(db, user, immeuble_id)
    # Nouveau code en fin de liste.
    derniere = (
        await db.execute(
            select(func.coalesce(func.max(ImmeubleCode.position), -1)).where(
                ImmeubleCode.immeuble_id == immeuble_id
            )
        )
    ).scalar_one()
    obj = ImmeubleCode(
        immeuble_id=immeuble_id,
        libelle=payload.libelle,
        code=payload.code,
        note=(payload.note or "").strip() or None,
        position=int(derniere or 0) + 1,
        created_by_email=getattr(user, "email", None),
    )
    now = datetime.now(timezone.utc)
    obj.created_at = now
    obj.updated_at = now
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return ImmeubleCodeRead.model_validate(obj)


@router.patch(
    "/immeubles/{immeuble_id}/codes/{code_id}",
    response_model=ImmeubleCodeRead,
    summary="Modifie un code d'accès (libellé, code, note, ordre)",
)
async def update_code_immeuble(
    immeuble_id: int,
    code_id: int,
    payload: ImmeubleCodeUpdate,
    db: DBSession,
    user: CurrentUser,
) -> ImmeubleCodeRead:
    _require_volet(user)
    await _immeuble_visible_ou_404(db, user, immeuble_id)
    obj = await _code_ou_404(db, immeuble_id, code_id)
    data = payload.model_dump(exclude_unset=True)
    if "note" in data:
        data["note"] = (data["note"] or "").strip() or None
    for k, v in data.items():
        setattr(obj, k, v)
    obj.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(obj)
    return ImmeubleCodeRead.model_validate(obj)


@router.delete(
    "/immeubles/{immeuble_id}/codes/{code_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire un code d'accès de l'immeuble",
)
async def delete_code_immeuble(
    immeuble_id: int, code_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    await _immeuble_visible_ou_404(db, user, immeuble_id)
    obj = await _code_ou_404(db, immeuble_id, code_id)
    await db.delete(obj)
    await db.commit()
