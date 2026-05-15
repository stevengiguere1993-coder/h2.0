"""CRUD pour les contrats de facturation sous-traitants par projet.

Chaque entrée définit comment refacturer au client final les heures /
factures émises par un sous-traitant donné sur un projet donné.
"""

from typing import List

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.project_subcontractor_contract import (
    ProjectSubcontractorContract,
)
from app.schemas.subcontractor_contract import (
    SubcontractorContractCreate,
    SubcontractorContractRead,
    SubcontractorContractUpdate,
)


router = APIRouter(
    prefix="/subcontractor-contracts", tags=["subcontractor-contracts"]
)


@router.post(
    "",
    response_model=SubcontractorContractRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract(
    data: SubcontractorContractCreate,
    db: DBSession,
    _: RequireManager,
):
    # Garde-fou applicatif : un seul contrat actif par couple
    # (projet, sous-traitant). L'unique constraint en BD verrouille
    # déjà mais on renvoie une 409 lisible plutôt qu'une 500.
    existing = (
        await db.execute(
            select(ProjectSubcontractorContract)
            .where(
                ProjectSubcontractorContract.project_id == data.project_id
            )
            .where(
                ProjectSubcontractorContract.sous_traitant_id
                == data.sous_traitant_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "Un contrat existe déjà pour ce sous-traitant sur ce "
                "projet. Édite-le plutôt que d'en créer un nouveau."
            ),
        )

    obj = ProjectSubcontractorContract(**data.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return SubcontractorContractRead.model_validate(obj)


@router.get(
    "",
    response_model=List[SubcontractorContractRead],
)
async def list_contracts(
    db: DBSession,
    _: CurrentUser,
    project_id: int | None = None,
):
    """Liste les contrats — filtrables par projet."""
    stmt = select(ProjectSubcontractorContract).order_by(
        ProjectSubcontractorContract.id.desc()
    )
    if project_id is not None:
        stmt = stmt.where(
            ProjectSubcontractorContract.project_id == project_id
        )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


@router.get("/{contract_id}", response_model=SubcontractorContractRead)
async def get_contract(contract_id: int, db: DBSession, _: CurrentUser):
    obj = (
        await db.execute(
            select(ProjectSubcontractorContract).where(
                ProjectSubcontractorContract.id == contract_id
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contract not found")
    return SubcontractorContractRead.model_validate(obj)


@router.patch("/{contract_id}", response_model=SubcontractorContractRead)
async def update_contract(
    contract_id: int,
    data: SubcontractorContractUpdate,
    db: DBSession,
    _: RequireManager,
):
    obj = (
        await db.execute(
            select(ProjectSubcontractorContract).where(
                ProjectSubcontractorContract.id == contract_id
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contract not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    return SubcontractorContractRead.model_validate(obj)


@router.delete(
    "/{contract_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_contract(
    contract_id: int, db: DBSession, _: RequireManager
):
    obj = (
        await db.execute(
            select(ProjectSubcontractorContract).where(
                ProjectSubcontractorContract.id == contract_id
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contract not found")
    await db.delete(obj)
    await db.flush()
