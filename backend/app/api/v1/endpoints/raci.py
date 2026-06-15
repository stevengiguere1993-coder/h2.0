"""API de la matrice RACI « Distribution des tâches »."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from app.api.deps import CurrentUser, DBSession
from app.models.employe import Employe
from app.models.raci import RaciActivity, RaciCell, RaciPerson, RaciPole
from app.models.user import User

router = APIRouter(prefix="/raci", tags=["raci"])

_VALID = {"R", "A", "C", "I"}

# Les 6 pôles par défaut (créés au premier chargement). On peut ensuite
# en ajouter / renommer / supprimer librement depuis la page.
_DEFAULT_POLES = [
    "Comptabilité",
    "Développement logiciel",
    "Prospection / Acquisition",
    "Construction",
    "Gestion locative",
    "Gestion d'entreprise",
]


# ── Schémas ────────────────────────────────────────────────────────────


class PoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    position: int


class PoleWrite(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)


class PersonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: Optional[int] = None
    name: str
    subtitle: Optional[str] = None
    position: int


class PersonCreate(BaseModel):
    user_id: int


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
    value: Optional[str] = None


class AvailableUser(BaseModel):
    user_id: int
    name: str
    subtitle: Optional[str] = None


class RaciBoard(BaseModel):
    poles: List[PoleRead]
    people: List[PersonRead]
    activities: List[ActivityRead]
    cells: List[CellRead]


# ── Helpers ────────────────────────────────────────────────────────────


async def _seed_poles_if_empty(db) -> None:
    count = (await db.execute(select(func.count(RaciPole.id)))).scalar() or 0
    if count == 0:
        for i, label in enumerate(_DEFAULT_POLES):
            db.add(RaciPole(label=label, position=i + 1))
        await db.commit()


async def _user_display(db, user: User) -> tuple[str, Optional[str]]:
    """Nom à afficher + sous-titre (rôle) pour un compte Kratos."""
    name = user.email
    if user.email:
        fn = (
            await db.execute(
                select(Employe.full_name).where(
                    func.lower(Employe.email) == user.email.lower()
                )
            )
        ).scalars().first()
        if fn:
            name = fn
    role = getattr(user, "role", None)
    return name, (str(role) if role else None)


# ── Lecture complète ───────────────────────────────────────────────────


@router.get("", response_model=RaciBoard)
async def get_board(db: DBSession, _: CurrentUser) -> RaciBoard:
    await _seed_poles_if_empty(db)
    poles = (
        await db.execute(
            select(RaciPole).order_by(RaciPole.position, RaciPole.id)
        )
    ).scalars().all()
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
    return RaciBoard(
        poles=poles, people=people, activities=activities, cells=cells
    )


# ── Comptes Kratos disponibles (pour ajouter une colonne) ──────────────


@router.get("/available-users", response_model=List[AvailableUser])
async def available_users(
    db: DBSession, _: CurrentUser
) -> List[AvailableUser]:
    taken = {
        row[0]
        for row in (
            await db.execute(
                select(RaciPerson.user_id).where(
                    RaciPerson.user_id.isnot(None)
                )
            )
        ).all()
    }
    users = (
        await db.execute(
            select(User).where(User.is_active.is_(True)).order_by(User.id)
        )
    ).scalars().all()
    out: List[AvailableUser] = []
    for u in users:
        if u.id in taken:
            continue
        name, sub = await _user_display(db, u)
        out.append(AvailableUser(user_id=u.id, name=name, subtitle=sub))
    return out


# ── Pôles ──────────────────────────────────────────────────────────────


@router.post(
    "/poles", response_model=PoleRead, status_code=status.HTTP_201_CREATED
)
async def create_pole(
    data: PoleWrite, db: DBSession, _: CurrentUser
) -> PoleRead:
    maxpos = (
        await db.execute(
            select(RaciPole.position).order_by(RaciPole.position.desc())
        )
    ).scalars().first()
    p = RaciPole(label=data.label.strip(), position=(maxpos or 0) + 1)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@router.put("/poles/{pole_id}", response_model=PoleRead)
async def update_pole(
    pole_id: int, data: PoleWrite, db: DBSession, _: CurrentUser
) -> PoleRead:
    p = await db.get(RaciPole, pole_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Introuvable.")
    old = p.label
    p.label = data.label.strip()
    # Cascade : les activités rattachées suivent le renommage.
    if old and old != p.label:
        await db.execute(
            update(RaciActivity)
            .where(RaciActivity.pole == old)
            .values(pole=p.label)
        )
    await db.commit()
    await db.refresh(p)
    return p


@router.delete("/poles/{pole_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pole(pole_id: int, db: DBSession, _: CurrentUser) -> None:
    p = await db.get(RaciPole, pole_id)
    if p is not None:
        await db.delete(p)
        await db.commit()


# ── Personnes (colonnes = comptes Kratos) ──────────────────────────────


@router.post(
    "/people", response_model=PersonRead, status_code=status.HTTP_201_CREATED
)
async def create_person(
    data: PersonCreate, db: DBSession, _: CurrentUser
) -> PersonRead:
    user = await db.get(User, data.user_id)
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Compte introuvable."
        )
    exists = (
        await db.execute(
            select(RaciPerson).where(RaciPerson.user_id == data.user_id)
        )
    ).scalar_one_or_none()
    if exists is not None:
        return exists
    name, sub = await _user_display(db, user)
    maxpos = (
        await db.execute(
            select(RaciPerson.position).order_by(RaciPerson.position.desc())
        )
    ).scalars().first()
    p = RaciPerson(
        user_id=user.id,
        name=name,
        subtitle=sub,
        position=(maxpos or 0) + 1,
    )
    db.add(p)
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
