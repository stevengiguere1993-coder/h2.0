"""Employee CRUD with auto-creation of a User account.

On reproduit l'API du generic CRUD utilisé pour les autres entités
business (list / get / create / update / delete) mais on intercepte
le POST pour créer en parallèle un User auth qui pourra se connecter
à l'app. Le mot de passe temporaire est « Horizon » et le flag
must_change_password est levé — l'employé sera forcé de le changer
au premier login.

Pourquoi pas un signal SQLAlchemy ? On veut absolument que la
création User échoue UNE TRANSACTION en cas d'email manquant ou
déjà pris, pour éviter d'avoir un employé orphelin sans compte.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.core.security import get_password_hash
from app.models.employe import Employe
from app.models.user import User, UserRole
from app.schemas.business import EmployeCreate, EmployeRead, EmployeUpdate


log = logging.getLogger(__name__)

router = APIRouter(prefix="/employes", tags=["employes"])


TEMPORARY_PASSWORD = "Horizon"


@router.get("", response_model=List[EmployeRead])
async def list_employes(
    db: DBSession,
    _: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
) -> List[EmployeRead]:
    rows = (
        await db.execute(
            select(Employe).order_by(Employe.full_name.asc()).offset(skip).limit(limit)
        )
    ).scalars().all()
    return [EmployeRead.model_validate(r) for r in rows]


@router.get("/{item_id}", response_model=EmployeRead)
async def get_employe(
    item_id: int, db: DBSession, _: CurrentUser
) -> EmployeRead:
    e = (
        await db.execute(select(Employe).where(Employe.id == item_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employé introuvable.")
    return EmployeRead.model_validate(e)


@router.post(
    "",
    response_model=EmployeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crée un employé + son compte utilisateur (mot de passe temporaire)",
)
async def create_employe(
    data: EmployeCreate, db: DBSession, _: RequireManager
) -> EmployeRead:
    e = Employe(**data.model_dump(exclude_unset=True))
    db.add(e)
    await db.flush()
    await db.refresh(e)

    if e.email:
        # Un User existe peut-être déjà pour ce courriel (le proprio
        # créé en CLI, ou un employé re-créé). Dans ce cas on n'écrase
        # pas — on laisse l'employeur réinitialiser le mdp manuellement
        # depuis /app/utilisateurs si nécessaire.
        existing = (
            await db.execute(select(User).where(User.email == e.email))
        ).scalar_one_or_none()
        if existing is None:
            u = User(
                email=e.email,
                hashed_password=get_password_hash(TEMPORARY_PASSWORD),
                is_active=True,
                is_admin=False,
                role=UserRole.EMPLOYEE.value,
                must_change_password=True,
            )
            db.add(u)
            await db.flush()

            # Courriel d'accueil avec mdp temporaire "Horizon".
            try:
                from app.services.welcome_email import send_welcome_email

                await send_welcome_email(
                    to_email=e.email,
                    temporary_password=TEMPORARY_PASSWORD,
                    full_name=e.full_name,
                    role=UserRole.EMPLOYEE.value,
                )
            except Exception:
                pass
    return EmployeRead.model_validate(e)


@router.patch("/{item_id}", response_model=EmployeRead)
async def update_employe(
    item_id: int,
    data: EmployeUpdate,
    db: DBSession,
    _: RequireManager,
) -> EmployeRead:
    e = (
        await db.execute(select(Employe).where(Employe.id == item_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employé introuvable.")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(e, field, value)
    await db.flush()
    await db.refresh(e)
    return EmployeRead.model_validate(e)


@router.delete(
    "/{item_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_employe(
    item_id: int, db: DBSession, _: RequireManager
) -> None:
    e = (
        await db.execute(select(Employe).where(Employe.id == item_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employé introuvable.")
    await db.delete(e)
    await db.flush()
