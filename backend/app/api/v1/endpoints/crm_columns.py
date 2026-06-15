"""Colonnes personnalisées du tableau CRM, persistées côté serveur.

Partagées par toute l'équipe (pas de localStorage) → une carte placée
dans « À rappeler » y reste sur tous les appareils.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.crm_column import CrmColumn
from app.schemas.crm_column import (
    CrmColumnCreate,
    CrmColumnRead,
    CrmColumnUpdate,
)

router = APIRouter(prefix="/crm/columns", tags=["crm-columns"])


@router.get("", response_model=list[CrmColumnRead])
async def list_columns(db: DBSession, _: CurrentUser) -> list[CrmColumnRead]:
    rows = (
        (
            await db.execute(
                select(CrmColumn).order_by(
                    CrmColumn.position.asc(), CrmColumn.id.asc()
                )
            )
        )
        .scalars()
        .all()
    )
    return [CrmColumnRead.model_validate(r) for r in rows]


@router.post("", response_model=CrmColumnRead, status_code=status.HTTP_201_CREATED)
async def create_column(
    data: CrmColumnCreate, db: DBSession, _: CurrentUser
) -> CrmColumnRead:
    # Upsert par `key` : idempotent, pratique pour la migration depuis
    # le localStorage (on re-poste les colonnes locales sans risque de
    # doublon).
    existing = (
        await db.execute(select(CrmColumn).where(CrmColumn.key == data.key))
    ).scalar_one_or_none()
    if existing is not None:
        existing.label = data.label
        if data.dot:
            existing.dot = data.dot
        existing.position = data.position
        await db.flush()
        return CrmColumnRead.model_validate(existing)
    col = CrmColumn(
        key=data.key,
        label=data.label,
        dot=data.dot or "bg-sky-400",
        position=data.position,
    )
    db.add(col)
    await db.flush()
    return CrmColumnRead.model_validate(col)


@router.patch("/{key}", response_model=CrmColumnRead)
async def update_column(
    key: str, data: CrmColumnUpdate, db: DBSession, _: CurrentUser
) -> CrmColumnRead:
    col = (
        await db.execute(select(CrmColumn).where(CrmColumn.key == key))
    ).scalar_one_or_none()
    if col is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Colonne introuvable.")
    if data.label is not None:
        col.label = data.label
    if data.dot is not None:
        col.dot = data.dot
    if data.position is not None:
        col.position = data.position
    await db.flush()
    return CrmColumnRead.model_validate(col)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_column(key: str, db: DBSession, _: CurrentUser) -> Response:
    col = (
        await db.execute(select(CrmColumn).where(CrmColumn.key == key))
    ).scalar_one_or_none()
    if col is not None:
        await db.delete(col)
        await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
