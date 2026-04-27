"""Endpoints CRUD pour les listes (segments) Prospection.

Une « liste » regroupe N leads selon des critères. Permet au prospecteur
de choisir un segment et travailler ses leads dedans.

Routes :
- GET    /prospection/lists                  → toutes les listes
- POST   /prospection/lists                  → créer une liste vide
- GET    /prospection/lists/{id}             → métadonnées + count
- PATCH  /prospection/lists/{id}             → renommer / éditer
- DELETE /prospection/lists/{id}             → supprimer la liste
- GET    /prospection/lists/{id}/members     → leads dans la liste
- POST   /prospection/lists/{id}/members     → ajouter lead_ids
- DELETE /prospection/lists/{id}/members     → retirer lead_ids
- POST   /prospection/lists/from-query       → List Builder : crée une
                                                 liste à partir de filtres
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, delete, func, select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.prospection_lead import ProspectionLead
from app.models.prospection_lead_list import (
    ProspectionLeadList,
    ProspectionLeadListMember,
)

router = APIRouter(prefix="/prospection/lists", tags=["prospection-lists"])


# ----------------------------- Schemas -----------------------------


class ListCriteria(BaseModel):
    """Critères du List Builder. Tous optionnels — on filtre seulement
    sur ce qui est fourni."""

    status: Optional[str] = None
    kind: Optional[str] = None
    city: Optional[str] = None
    owner_kind: Optional[str] = None
    min_logements: Optional[int] = Field(default=None, ge=0)
    max_logements: Optional[int] = Field(default=None, ge=0)
    min_score: Optional[int] = Field(default=None, ge=0, le=100)
    max_score: Optional[int] = Field(default=None, ge=0, le=100)
    min_annee: Optional[int] = None
    max_annee: Optional[int] = None
    min_valeur: Optional[float] = Field(default=None, ge=0)
    max_valeur: Optional[float] = Field(default=None, ge=0)
    tax_delinquent: Optional[bool] = None
    archived: Optional[bool] = False


class ListRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str]
    criteria_json: Optional[str]
    created_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    member_count: int = 0


class ListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = None
    criteria: Optional[ListCriteria] = None


class ListUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    criteria: Optional[ListCriteria] = None


class MembersIn(BaseModel):
    lead_ids: List[int] = Field(min_length=1, max_length=5000)


class FromQueryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = None
    criteria: ListCriteria


# ----------------------------- Helpers -----------------------------


def _build_query_from_criteria(c: ListCriteria):
    """Construit un select(ProspectionLead) avec les filtres du criteria."""
    stmt = select(ProspectionLead).where(
        ProspectionLead.archived == bool(c.archived)
    )
    if c.status:
        stmt = stmt.where(ProspectionLead.status == c.status)
    if c.kind:
        stmt = stmt.where(ProspectionLead.kind == c.kind)
    if c.city:
        # ilike pour tolérance casse/accent côté Postgres
        stmt = stmt.where(ProspectionLead.city.ilike(f"%{c.city}%"))
    if c.owner_kind:
        stmt = stmt.where(ProspectionLead.owner_kind == c.owner_kind)
    if c.min_logements is not None:
        stmt = stmt.where(ProspectionLead.nb_logements >= c.min_logements)
    if c.max_logements is not None:
        stmt = stmt.where(ProspectionLead.nb_logements <= c.max_logements)
    if c.min_score is not None:
        stmt = stmt.where(ProspectionLead.score >= c.min_score)
    if c.max_score is not None:
        stmt = stmt.where(ProspectionLead.score <= c.max_score)
    if c.min_annee is not None:
        stmt = stmt.where(ProspectionLead.annee_construction >= c.min_annee)
    if c.max_annee is not None:
        stmt = stmt.where(ProspectionLead.annee_construction <= c.max_annee)
    if c.min_valeur is not None:
        stmt = stmt.where(ProspectionLead.valeur_fonciere >= c.min_valeur)
    if c.max_valeur is not None:
        stmt = stmt.where(ProspectionLead.valeur_fonciere <= c.max_valeur)
    if c.tax_delinquent is not None:
        stmt = stmt.where(
            ProspectionLead.tax_delinquent == c.tax_delinquent
        )
    return stmt


async def _count_members(db, list_id: int) -> int:
    res = await db.execute(
        select(func.count(ProspectionLeadListMember.lead_id)).where(
            ProspectionLeadListMember.list_id == list_id
        )
    )
    return int(res.scalar() or 0)


def _serialize(lst: ProspectionLeadList, count: int) -> ListRead:
    obj = ListRead.model_validate(lst)
    obj.member_count = count
    return obj


# ----------------------------- Endpoints -----------------------------


@router.get("", response_model=List[ListRead])
async def list_all(db: DBSession, _: CurrentUser) -> List[ListRead]:
    rows = (
        await db.execute(
            select(ProspectionLeadList).order_by(
                ProspectionLeadList.updated_at.desc()
            )
        )
    ).scalars().all()
    if not rows:
        return []
    # Compteur en une seule query groupée — pas de N+1.
    counts_rows = (
        await db.execute(
            select(
                ProspectionLeadListMember.list_id,
                func.count(ProspectionLeadListMember.lead_id),
            ).group_by(ProspectionLeadListMember.list_id)
        )
    ).all()
    counts = {r[0]: int(r[1]) for r in counts_rows}
    return [_serialize(r, counts.get(r.id, 0)) for r in rows]


@router.post(
    "",
    response_model=ListRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_list(
    data: ListCreate, db: DBSession, user: RequireManager
) -> ListRead:
    lst = ProspectionLeadList(
        name=data.name.strip(),
        description=(data.description or "").strip() or None,
        criteria_json=(
            json.dumps(data.criteria.model_dump(exclude_none=True))
            if data.criteria
            else None
        ),
        created_by_user_id=user.id,
    )
    db.add(lst)
    await db.flush()
    await db.refresh(lst)
    return _serialize(lst, 0)


@router.get("/{list_id}", response_model=ListRead)
async def get_list(
    list_id: int, db: DBSession, _: CurrentUser
) -> ListRead:
    lst = (
        await db.execute(
            select(ProspectionLeadList).where(
                ProspectionLeadList.id == list_id
            )
        )
    ).scalar_one_or_none()
    if lst is None:
        raise HTTPException(404, "Liste introuvable.")
    count = await _count_members(db, list_id)
    return _serialize(lst, count)


@router.patch("/{list_id}", response_model=ListRead)
async def update_list(
    list_id: int,
    data: ListUpdate,
    db: DBSession,
    _: RequireManager,
) -> ListRead:
    lst = (
        await db.execute(
            select(ProspectionLeadList).where(
                ProspectionLeadList.id == list_id
            )
        )
    ).scalar_one_or_none()
    if lst is None:
        raise HTTPException(404, "Liste introuvable.")
    if data.name is not None:
        lst.name = data.name.strip()
    if data.description is not None:
        lst.description = data.description.strip() or None
    if data.criteria is not None:
        lst.criteria_json = json.dumps(
            data.criteria.model_dump(exclude_none=True)
        )
    await db.flush()
    await db.refresh(lst)
    count = await _count_members(db, list_id)
    return _serialize(lst, count)


@router.delete(
    "/{list_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_list(
    list_id: int, db: DBSession, _: RequireManager
) -> None:
    res = await db.execute(
        delete(ProspectionLeadList).where(
            ProspectionLeadList.id == list_id
        )
    )
    if (res.rowcount or 0) == 0:
        raise HTTPException(404, "Liste introuvable.")


# --------------------------- Members ---------------------------


@router.get("/{list_id}/members")
async def get_members(
    list_id: int, db: DBSession, _: CurrentUser
) -> dict:
    """Retourne les leads membres + l'objet liste."""
    lst = (
        await db.execute(
            select(ProspectionLeadList).where(
                ProspectionLeadList.id == list_id
            )
        )
    ).scalar_one_or_none()
    if lst is None:
        raise HTTPException(404, "Liste introuvable.")

    member_ids = (
        await db.execute(
            select(ProspectionLeadListMember.lead_id).where(
                ProspectionLeadListMember.list_id == list_id
            )
        )
    ).scalars().all()

    leads: list = []
    if member_ids:
        leads = list(
            (
                await db.execute(
                    select(ProspectionLead).where(
                        ProspectionLead.id.in_(member_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
    return {
        "list": _serialize(lst, len(member_ids)),
        "lead_ids": list(member_ids),
        # On retourne juste les IDs ici ; le frontend re-fetch
        # /prospection?... pour avoir les détails complets s'il en
        # a besoin. Évite la duplication de logique de sérialisation.
    }


@router.post("/{list_id}/members", response_model=ListRead)
async def add_members(
    list_id: int,
    data: MembersIn,
    db: DBSession,
    _: RequireManager,
) -> ListRead:
    lst = (
        await db.execute(
            select(ProspectionLeadList).where(
                ProspectionLeadList.id == list_id
            )
        )
    ).scalar_one_or_none()
    if lst is None:
        raise HTTPException(404, "Liste introuvable.")

    # Récupère les leads existants pour éviter les FK invalides
    existing_lead_rows = (
        await db.execute(
            select(ProspectionLead.id).where(
                ProspectionLead.id.in_(data.lead_ids)
            )
        )
    ).scalars().all()
    valid_ids = set(existing_lead_rows)

    # Évite les doublons
    already_member_rows = (
        await db.execute(
            select(ProspectionLeadListMember.lead_id).where(
                and_(
                    ProspectionLeadListMember.list_id == list_id,
                    ProspectionLeadListMember.lead_id.in_(valid_ids),
                )
            )
        )
    ).scalars().all()
    already = set(already_member_rows)

    to_add = valid_ids - already
    for lid in to_add:
        db.add(
            ProspectionLeadListMember(list_id=list_id, lead_id=lid)
        )
    await db.flush()
    count = await _count_members(db, list_id)
    await db.refresh(lst)
    return _serialize(lst, count)


@router.delete("/{list_id}/members", response_model=ListRead)
async def remove_members(
    list_id: int,
    data: MembersIn,
    db: DBSession,
    _: RequireManager,
) -> ListRead:
    lst = (
        await db.execute(
            select(ProspectionLeadList).where(
                ProspectionLeadList.id == list_id
            )
        )
    ).scalar_one_or_none()
    if lst is None:
        raise HTTPException(404, "Liste introuvable.")
    await db.execute(
        delete(ProspectionLeadListMember).where(
            and_(
                ProspectionLeadListMember.list_id == list_id,
                ProspectionLeadListMember.lead_id.in_(data.lead_ids),
            )
        )
    )
    await db.flush()
    count = await _count_members(db, list_id)
    await db.refresh(lst)
    return _serialize(lst, count)


# --------------------------- List Builder ---------------------------


@router.post(
    "/from-query",
    response_model=ListRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crée une liste à partir de critères (List Builder). "
    "Matérialise les leads correspondants au moment de la création.",
)
async def create_from_query(
    data: FromQueryIn, db: DBSession, user: RequireManager
) -> ListRead:
    # 1. Créer la liste
    lst = ProspectionLeadList(
        name=data.name.strip(),
        description=(data.description or "").strip() or None,
        criteria_json=json.dumps(
            data.criteria.model_dump(exclude_none=True)
        ),
        created_by_user_id=user.id,
    )
    db.add(lst)
    await db.flush()
    await db.refresh(lst)

    # 2. Matérialiser les leads matchant
    stmt = _build_query_from_criteria(data.criteria)
    lead_rows = (await db.execute(stmt)).scalars().all()
    for lead in lead_rows:
        db.add(
            ProspectionLeadListMember(
                list_id=lst.id, lead_id=lead.id
            )
        )
    await db.flush()
    return _serialize(lst, len(lead_rows))


@router.post(
    "/{list_id}/rebuild",
    response_model=ListRead,
    summary="Re-matérialise une liste construite via filtres : "
    "écrase les membres actuels avec ce que retourne le criteria.",
)
async def rebuild_from_criteria(
    list_id: int, db: DBSession, _: RequireManager
) -> ListRead:
    lst = (
        await db.execute(
            select(ProspectionLeadList).where(
                ProspectionLeadList.id == list_id
            )
        )
    ).scalar_one_or_none()
    if lst is None:
        raise HTTPException(404, "Liste introuvable.")
    if not lst.criteria_json:
        raise HTTPException(
            400,
            "Cette liste n'a pas de critères enregistrés (manuelle).",
        )
    try:
        criteria = ListCriteria.model_validate_json(lst.criteria_json)
    except Exception as exc:
        raise HTTPException(
            500, f"Critères corrompus : {exc}"
        ) from exc

    # Vide la liste
    await db.execute(
        delete(ProspectionLeadListMember).where(
            ProspectionLeadListMember.list_id == list_id
        )
    )
    # Re-matérialise
    stmt = _build_query_from_criteria(criteria)
    lead_rows = (await db.execute(stmt)).scalars().all()
    for lead in lead_rows:
        db.add(
            ProspectionLeadListMember(
                list_id=list_id, lead_id=lead.id
            )
        )
    await db.flush()
    await db.refresh(lst)
    return _serialize(lst, len(lead_rows))
