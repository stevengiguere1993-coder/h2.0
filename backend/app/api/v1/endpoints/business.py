"""Generic CRUD endpoints for business entities.

All endpoints require an authenticated user.
"""

from typing import List, Type

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.db.base import Base
from app.models.achat import Achat
from app.models.agenda_event import AgendaEvent
from app.models.bon_travail import BonTravail
from app.models.employe import Employe
from app.models.facture import Facture
from app.models.fournisseur import Fournisseur
from app.models.punch import Punch
from app.models.soumission import Soumission
from app.models.sous_traitant import SousTraitant
from app.repositories.generic import GenericCrud
from app.schemas.business import (
    AchatCreate,
    AchatRead,
    AchatUpdate,
    AgendaEventCreate,
    AgendaEventRead,
    AgendaEventUpdate,
    BonTravailCreate,
    BonTravailRead,
    BonTravailUpdate,
    EmployeCreate,
    EmployeRead,
    EmployeUpdate,
    FactureCreate,
    FactureRead,
    FactureUpdate,
    FournisseurCreate,
    FournisseurRead,
    FournisseurUpdate,
    PunchCreate,
    PunchRead,
    PunchUpdate,
    SoumissionCreate,
    SoumissionRead,
    SoumissionUpdate,
)
from app.schemas.sous_traitant import (
    SousTraitantCreate,
    SousTraitantRead,
    SousTraitantUpdate,
)


def make_crud_router(
    *,
    prefix: str,
    tag: str,
    model: Type[Base],
    create_schema: Type[BaseModel],
    update_schema: Type[BaseModel],
    read_schema: Type[BaseModel],
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create(data: create_schema, db: DBSession, _: CurrentUser):  # type: ignore[valid-type]
        crud = GenericCrud(db, model)
        obj = await crud.create(data)
        return read_schema.model_validate(obj)

    @router.get("", response_model=List[read_schema])  # type: ignore[valid-type]
    async def list_items(
        db: DBSession,
        _: CurrentUser,
        skip: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
    ):
        crud = GenericCrud(db, model)
        items = await crud.list(skip=skip, limit=limit)
        return [read_schema.model_validate(i) for i in items]

    @router.get("/{item_id}")
    async def get_item(item_id: int, db: DBSession, _: CurrentUser):
        crud = GenericCrud(db, model)
        obj = await crud.get(item_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        return read_schema.model_validate(obj)

    @router.patch("/{item_id}")
    async def update_item(item_id: int, data: update_schema, db: DBSession, _: CurrentUser):  # type: ignore[valid-type]
        crud = GenericCrud(db, model)
        obj = await crud.get(item_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        obj = await crud.update(obj, data)
        return read_schema.model_validate(obj)

    @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_item(item_id: int, db: DBSession, _: CurrentUser):
        crud = GenericCrud(db, model)
        obj = await crud.get(item_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        await crud.delete(obj)

    return router


employes_router = make_crud_router(
    prefix="/employes", tag="employes",
    model=Employe, create_schema=EmployeCreate, update_schema=EmployeUpdate, read_schema=EmployeRead,
)
fournisseurs_router = make_crud_router(
    prefix="/fournisseurs", tag="fournisseurs",
    model=Fournisseur, create_schema=FournisseurCreate, update_schema=FournisseurUpdate, read_schema=FournisseurRead,
)
sous_traitants_router = make_crud_router(
    prefix="/sous-traitants", tag="sous-traitants",
    model=SousTraitant, create_schema=SousTraitantCreate, update_schema=SousTraitantUpdate, read_schema=SousTraitantRead,
)
soumissions_router = make_crud_router(
    prefix="/soumissions", tag="soumissions",
    model=Soumission, create_schema=SoumissionCreate, update_schema=SoumissionUpdate, read_schema=SoumissionRead,
)
agenda_router = make_crud_router(
    prefix="/agenda", tag="agenda",
    model=AgendaEvent, create_schema=AgendaEventCreate, update_schema=AgendaEventUpdate, read_schema=AgendaEventRead,
)
bons_router = make_crud_router(
    prefix="/bons-travail", tag="bons-travail",
    model=BonTravail, create_schema=BonTravailCreate, update_schema=BonTravailUpdate, read_schema=BonTravailRead,
)
punch_router = make_crud_router(
    prefix="/punch", tag="punch",
    model=Punch, create_schema=PunchCreate, update_schema=PunchUpdate, read_schema=PunchRead,
)
factures_router = make_crud_router(
    prefix="/factures", tag="factures",
    model=Facture, create_schema=FactureCreate, update_schema=FactureUpdate, read_schema=FactureRead,
)
achats_router = make_crud_router(
    prefix="/achats", tag="achats",
    model=Achat, create_schema=AchatCreate, update_schema=AchatUpdate, read_schema=AchatRead,
)
