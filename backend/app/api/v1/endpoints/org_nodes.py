"""Endpoints CRUD pour l'organigramme.

  GET    /api/v1/org-nodes              liste plate (l'UI reconstruit
                                        l'arbre)
  POST   /api/v1/org-nodes              crée un nœud
  GET    /api/v1/org-nodes/{id}         détail
  PATCH  /api/v1/org-nodes/{id}         édite (label, parent, assignee,
                                        entreprise, position, ...)
  DELETE /api/v1/org-nodes/{id}         supprime (cascade sur enfants)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.org_node import OrgNode


log = logging.getLogger(__name__)
router = APIRouter(prefix="/org-nodes", tags=["org-nodes"])


VALID_KINDS = {"dept", "role", "service", "task"}


class OrgNodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    parent_id: Optional[int]
    position: int
    kind: str
    label: str
    description: Optional[str]
    entreprise_id: Optional[int]
    assignee_employe_id: Optional[int]
    assignee_user_id: Optional[int]
    assignee_external_name: Optional[str]
    created_at: datetime
    updated_at: datetime


class OrgNodeCreate(BaseModel):
    parent_id: Optional[int] = None
    position: Optional[int] = None
    kind: str = Field(default="dept", max_length=16)
    label: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    entreprise_id: Optional[int] = None
    assignee_employe_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    assignee_external_name: Optional[str] = Field(
        default=None, max_length=255
    )


class OrgNodeUpdate(BaseModel):
    parent_id: Optional[int] = None
    position: Optional[int] = None
    kind: Optional[str] = Field(default=None, max_length=16)
    label: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    entreprise_id: Optional[int] = None
    assignee_employe_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    assignee_external_name: Optional[str] = Field(
        default=None, max_length=255
    )


@router.get("", response_model=List[OrgNodeRead])
async def list_nodes(
    db: DBSession,
    _: CurrentUser,
    entreprise_id: Optional[int] = Query(default=None),
) -> List[OrgNodeRead]:
    stmt = (
        select(OrgNode)
        .order_by(OrgNode.parent_id.asc().nulls_first(), OrgNode.position.asc())
    )
    if entreprise_id is not None:
        stmt = stmt.where(OrgNode.entreprise_id == entreprise_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [OrgNodeRead.model_validate(r) for r in rows]


@router.post(
    "", response_model=OrgNodeRead, status_code=status.HTTP_201_CREATED
)
async def create_node(
    data: OrgNodeCreate, db: DBSession, _: CurrentUser
) -> OrgNodeRead:
    kind = data.kind if data.kind in VALID_KINDS else "dept"
    # Position auto si non fournie : max(siblings) + 1
    if data.position is None:
        sibling = (
            await db.execute(
                select(OrgNode)
                .where(OrgNode.parent_id.is_(data.parent_id))
                if data.parent_id is None
                else select(OrgNode).where(OrgNode.parent_id == data.parent_id)
            )
        ).scalars().all()
        pos = max((s.position for s in sibling), default=-1) + 1
    else:
        pos = int(data.position)
    n = OrgNode(
        parent_id=data.parent_id,
        position=pos,
        kind=kind,
        label=data.label.strip(),
        description=data.description,
        entreprise_id=data.entreprise_id,
        assignee_employe_id=data.assignee_employe_id,
        assignee_user_id=data.assignee_user_id,
        assignee_external_name=data.assignee_external_name,
    )
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return OrgNodeRead.model_validate(n)


@router.get("/{node_id}", response_model=OrgNodeRead)
async def get_node(
    node_id: int, db: DBSession, _: CurrentUser
) -> OrgNodeRead:
    n = (
        await db.execute(select(OrgNode).where(OrgNode.id == node_id))
    ).scalar_one_or_none()
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nœud introuvable.")
    return OrgNodeRead.model_validate(n)


@router.patch("/{node_id}", response_model=OrgNodeRead)
async def update_node(
    node_id: int,
    data: OrgNodeUpdate,
    db: DBSession,
    _: CurrentUser,
) -> OrgNodeRead:
    n = (
        await db.execute(select(OrgNode).where(OrgNode.id == node_id))
    ).scalar_one_or_none()
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nœud introuvable.")
    payload = data.model_dump(exclude_unset=True)
    if "kind" in payload and payload["kind"] not in VALID_KINDS:
        payload.pop("kind")
    for k, v in payload.items():
        setattr(n, k, v)
    await db.commit()
    await db.refresh(n)
    return OrgNodeRead.model_validate(n)


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    node_id: int, db: DBSession, _: CurrentUser
) -> None:
    n = (
        await db.execute(select(OrgNode).where(OrgNode.id == node_id))
    ).scalar_one_or_none()
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nœud introuvable.")
    await db.delete(n)
    await db.commit()
