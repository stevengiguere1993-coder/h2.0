"""API de la matrice RACI « Distribution des tâches »."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.raci import RaciActivity, RaciCell, RaciPerson

router = APIRouter(prefix="/raci", tags=["raci"])

_VALID = {"R", "A", "C", "I"}


# ── Schémas ────────────────────────────────────────────────────────────


class PersonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    subtitle: Optional[str] = None
    position: int


class PersonWrite(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    subtitle: Optional[str] = Field(default=None, max_length=120)


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    pole: str
    label: str
    position: int


class ActivityWrite(BaseModel):
    pole: str = Field(default="", max_length=120)
    label: str = Field(..., min_length=1, max_length=300)


class CellRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    activity_id: int
    person_id: int
    value: str


class CellWrite(BaseModel):
    activity_id: int
    person_id: int
    value: Optional[str] = None  # vide/None → efface la cellule


class RaciBoard(BaseModel):
    people: List[PersonRead]
    activities: List[ActivityRead]
    cells: List[CellRead]


# ── Lecture complète ───────────────────────────────────────────────────


@router.get("", response_model=RaciBoard)
async def get_board(db: DBSession, _: CurrentUser) -> RaciBoard:
    people = (
        await db.execute(
            select(RaciPerson).order_by(RaciPerson.position, RaciPerson.id)
        )
    ).scalars().all()
    activities = (
        await db.execute(
            select(RaciActivity).order_by(
                RaciActivity.pole, RaciActivity.position, RaciActivity.id
            )
        )
    ).scalars().all()
    cells = (await db.execute(select(RaciCell))).scalars().all()
    return RaciBoard(people=people, activities=activities, cells=cells)


# ── Personnes (colonnes) ───────────────────────────────────────────────


@router.post(
    "/people", response_model=PersonRead, status_code=status.HTTP_201_CREATED
)
async def create_person(
    data: PersonWrite, db: DBSession, _: CurrentUser
) -> PersonRead:
    maxpos = (
        await db.execute(
            select(RaciPerson.position).order_by(RaciPerson.position.desc())
        )
    ).scalars().first()
    p = RaciPerson(
        name=data.name.strip(),
        subtitle=(data.subtitle or None),
        position=(maxpos or 0) + 1,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@router.put("/people/{person_id}", response_model=PersonRead)
async def update_person(
    person_id: int, data: PersonWrite, db: DBSession, _: CurrentUser
) -> PersonRead:
    p = await db.get(RaciPerson, person_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Introuvable.")
    p.name = data.name.strip()
    p.subtitle = data.subtitle or None
    await db.commit()
    await db.refresh(p)
    return p


@router.delete("/people/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(
    person_id: int, db: DBSession, _: CurrentUser
) -> None:
    p = await db.get(RaciPerson, person_id)
    if p is not None:
        await db.delete(p)
        await db.commit()


# ── Activités (lignes) ─────────────────────────────────────────────────


@router.post(
    "/activities",
    response_model=ActivityRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_activity(
    data: ActivityWrite, db: DBSession, _: CurrentUser
) -> ActivityRead:
    maxpos = (
        await db.execute(
            select(RaciActivity.position).order_by(
                RaciActivity.position.desc()
            )
        )
    ).scalars().first()
    a = RaciActivity(
        pole=data.pole.strip(),
        label=data.label.strip(),
        position=(maxpos or 0) + 1,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


@router.put("/activities/{activity_id}", response_model=ActivityRead)
async def update_activity(
    activity_id: int, data: ActivityWrite, db: DBSession, _: CurrentUser
) -> ActivityRead:
    a = await db.get(RaciActivity, activity_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Introuvable.")
    a.pole = data.pole.strip()
    a.label = data.label.strip()
    await db.commit()
    await db.refresh(a)
    return a


@router.delete(
    "/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_activity(
    activity_id: int, db: DBSession, _: CurrentUser
) -> None:
    a = await db.get(RaciActivity, activity_id)
    if a is not None:
        await db.delete(a)
        await db.commit()


# ── Cellule (upsert R/A/C/I, vide = efface) ────────────────────────────


@router.put("/cell", response_model=Optional[CellRead])
async def set_cell(
    data: CellWrite, db: DBSession, _: CurrentUser
) -> Optional[CellRead]:
    val = (data.value or "").strip().upper()
    existing = (
        await db.execute(
            select(RaciCell).where(
                RaciCell.activity_id == data.activity_id,
                RaciCell.person_id == data.person_id,
            )
        )
    ).scalar_one_or_none()

    if val not in _VALID:
        if existing is not None:
            await db.delete(existing)
            await db.commit()
        return None

    if existing is not None:
        existing.value = val
    else:
        # Garde-fou : l'activité et la personne doivent exister.
        if (await db.get(RaciActivity, data.activity_id)) is None or (
            await db.get(RaciPerson, data.person_id)
        ) is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="Ligne/colonne introuvable."
            )
        existing = RaciCell(
            activity_id=data.activity_id,
            person_id=data.person_id,
            value=val,
        )
        db.add(existing)
    await db.commit()
    await db.refresh(existing)
    return existing
