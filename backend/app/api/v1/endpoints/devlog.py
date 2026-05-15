"""Endpoints — pôle Développement logiciel.

Ressources :
  * /api/v1/devlog/clients — clients du pôle (boîtes pour qui on
    développe des plateformes / logiciels) ;
  * /api/v1/devlog/leads — pipeline kanban du closer ;
  * /api/v1/devlog/soumissions — devis envoyés aux leads / clients.

Accessible à tout utilisateur authentifié : nouveau pôle interne,
petite équipe (closer / PM / devs partagent l'outil).
"""

from typing import List, Type

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.db.base import Base
from app.models.devlog_client import DevlogClient
from app.models.devlog_invoice import DevlogInvoice
from app.models.devlog_lead import LEAD_STATUSES, DevlogLead
from app.models.devlog_project import DevlogProject
from app.models.devlog_soumission import DevlogSoumission
from app.models.devlog_soumission_item import DevlogSoumissionItem
from app.models.devlog_time_entry import DevlogTimeEntry
from app.repositories.generic import GenericCrud
from app.schemas.devlog import (
    DevlogClientCreate,
    DevlogClientRead,
    DevlogClientUpdate,
    DevlogInvoiceCreate,
    DevlogInvoiceRead,
    DevlogInvoiceUpdate,
    DevlogLeadCreate,
    DevlogLeadRead,
    DevlogLeadStatusUpdate,
    DevlogLeadUpdate,
    DevlogProjectCreate,
    DevlogProjectRead,
    DevlogProjectUpdate,
    DevlogSoumissionCreate,
    DevlogSoumissionItemCreate,
    DevlogSoumissionItemRead,
    DevlogSoumissionItemUpdate,
    DevlogSoumissionRead,
    DevlogSoumissionUpdate,
    DevlogTimeEntryCreate,
    DevlogTimeEntryRead,
    DevlogTimeEntryUpdate,
)


def _make_crud_router(
    *,
    prefix: str,
    model: Type[Base],
    create_schema: Type[BaseModel],
    update_schema: Type[BaseModel],
    read_schema: Type[BaseModel],
    not_found: str,
) -> APIRouter:
    """CRUD générique du pôle — ouvert à tout utilisateur authentifié.

    Diffère de ``business.make_crud_router`` : ici les écritures ne
    sont pas réservées aux managers (petit pôle interne partagé)."""
    router = APIRouter(prefix=prefix, tags=["devlog"])

    @router.post(
        "", response_model=read_schema, status_code=status.HTTP_201_CREATED
    )
    async def create(data: create_schema, db: DBSession, _: CurrentUser):  # type: ignore[valid-type]
        obj = await GenericCrud(db, model).create(data)
        return read_schema.model_validate(obj)

    @router.get("", response_model=List[read_schema])  # type: ignore[valid-type]
    async def list_items(
        db: DBSession,
        _: CurrentUser,
        skip: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=500),
    ):
        return list(await GenericCrud(db, model).list(skip=skip, limit=limit))

    @router.get("/{item_id}", response_model=read_schema)
    async def get_item(item_id: int, db: DBSession, _: CurrentUser):
        obj = await GenericCrud(db, model).get(item_id)
        if obj is None:
            raise HTTPException(status_code=404, detail=not_found)
        return read_schema.model_validate(obj)

    @router.patch("/{item_id}", response_model=read_schema)
    async def update_item(
        item_id: int, data: update_schema, db: DBSession, _: CurrentUser  # type: ignore[valid-type]
    ):
        crud = GenericCrud(db, model)
        obj = await crud.get(item_id)
        if obj is None:
            raise HTTPException(status_code=404, detail=not_found)
        obj = await crud.update(obj, data)
        return read_schema.model_validate(obj)

    @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_item(item_id: int, db: DBSession, _: CurrentUser):
        crud = GenericCrud(db, model)
        obj = await crud.get(item_id)
        if obj is None:
            raise HTTPException(status_code=404, detail=not_found)
        await crud.delete(obj)

    return router

# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------

clients_router = APIRouter(prefix="/devlog/clients", tags=["devlog"])


@clients_router.post(
    "", response_model=DevlogClientRead, status_code=status.HTTP_201_CREATED
)
async def create_client(
    data: DevlogClientCreate, db: DBSession, _: CurrentUser
):
    crud = GenericCrud(db, DevlogClient)
    obj = await crud.create(data)
    return DevlogClientRead.model_validate(obj)


@clients_router.get("", response_model=List[DevlogClientRead])
async def list_clients(
    db: DBSession,
    _: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
):
    crud = GenericCrud(db, DevlogClient)
    return list(await crud.list(skip=skip, limit=limit))


@clients_router.get("/{client_id}", response_model=DevlogClientRead)
async def get_client(client_id: int, db: DBSession, _: CurrentUser):
    crud = GenericCrud(db, DevlogClient)
    obj = await crud.get(client_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return DevlogClientRead.model_validate(obj)


@clients_router.patch("/{client_id}", response_model=DevlogClientRead)
async def update_client(
    client_id: int,
    data: DevlogClientUpdate,
    db: DBSession,
    _: CurrentUser,
):
    crud = GenericCrud(db, DevlogClient)
    obj = await crud.get(client_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Client introuvable")
    obj = await crud.update(obj, data)
    return DevlogClientRead.model_validate(obj)


@clients_router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(client_id: int, db: DBSession, _: CurrentUser):
    crud = GenericCrud(db, DevlogClient)
    obj = await crud.get(client_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Client introuvable")
    await crud.delete(obj)


# --------------------------------------------------------------------------
# Leads (pipeline du closer)
# --------------------------------------------------------------------------

leads_router = APIRouter(prefix="/devlog/leads", tags=["devlog"])


@leads_router.post(
    "", response_model=DevlogLeadRead, status_code=status.HTTP_201_CREATED
)
async def create_lead(data: DevlogLeadCreate, db: DBSession, _: CurrentUser):
    if data.status not in LEAD_STATUSES:
        raise HTTPException(status_code=422, detail="Statut invalide")
    crud = GenericCrud(db, DevlogLead)
    obj = await crud.create(data)
    return DevlogLeadRead.model_validate(obj)


@leads_router.get("", response_model=List[DevlogLeadRead])
async def list_leads(
    db: DBSession,
    _: CurrentUser,
    status_filter: str | None = Query(default=None, alias="status"),
):
    """Liste les leads, triés pour alimenter directement le kanban
    (par colonne de statut puis position)."""
    stmt = select(DevlogLead)
    if status_filter:
        stmt = stmt.where(DevlogLead.status == status_filter)
    stmt = stmt.order_by(DevlogLead.position.asc(), DevlogLead.id.desc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


@leads_router.get("/{lead_id}", response_model=DevlogLeadRead)
async def get_lead(lead_id: int, db: DBSession, _: CurrentUser):
    crud = GenericCrud(db, DevlogLead)
    obj = await crud.get(lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    return DevlogLeadRead.model_validate(obj)


@leads_router.patch("/{lead_id}", response_model=DevlogLeadRead)
async def update_lead(
    lead_id: int, data: DevlogLeadUpdate, db: DBSession, _: CurrentUser
):
    crud = GenericCrud(db, DevlogLead)
    obj = await crud.get(lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    if data.status is not None and data.status not in LEAD_STATUSES:
        raise HTTPException(status_code=422, detail="Statut invalide")
    obj = await crud.update(obj, data)
    return DevlogLeadRead.model_validate(obj)


@leads_router.patch("/{lead_id}/status", response_model=DevlogLeadRead)
async def move_lead(
    lead_id: int,
    data: DevlogLeadStatusUpdate,
    db: DBSession,
    _: CurrentUser,
):
    """Déplace un lead dans le kanban (drag & drop entre colonnes)."""
    if data.status not in LEAD_STATUSES:
        raise HTTPException(status_code=422, detail="Statut invalide")
    crud = GenericCrud(db, DevlogLead)
    obj = await crud.get(lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    obj.status = data.status
    if data.position is not None:
        obj.position = data.position
    await db.flush()
    await db.refresh(obj)
    return DevlogLeadRead.model_validate(obj)


@leads_router.post(
    "/{lead_id}/convert", response_model=DevlogClientRead
)
async def convert_lead_to_client(
    lead_id: int, db: DBSession, _: CurrentUser
):
    """Convertit un lead « gagné » en client du pôle. Idempotent :
    si le lead a déjà un client lié, on renvoie ce client."""
    lead_crud = GenericCrud(db, DevlogLead)
    lead = await lead_crud.get(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead introuvable")

    client_crud = GenericCrud(db, DevlogClient)
    if lead.client_id is not None:
        existing = await client_crud.get(lead.client_id)
        if existing is not None:
            return DevlogClientRead.model_validate(existing)

    client = DevlogClient(
        name=lead.name,
        company=lead.company,
        email=lead.email,
        phone=lead.phone,
        notes=lead.project_summary,
        status="active",
    )
    db.add(client)
    await db.flush()
    await db.refresh(client)

    lead.client_id = client.id
    lead.status = "gagne"
    await db.flush()

    return DevlogClientRead.model_validate(client)


@leads_router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(lead_id: int, db: DBSession, _: CurrentUser):
    crud = GenericCrud(db, DevlogLead)
    obj = await crud.get(lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    await crud.delete(obj)


# --------------------------------------------------------------------------
# Soumissions (devis)
# --------------------------------------------------------------------------

soumissions_router = _make_crud_router(
    prefix="/devlog/soumissions",
    model=DevlogSoumission,
    create_schema=DevlogSoumissionCreate,
    update_schema=DevlogSoumissionUpdate,
    read_schema=DevlogSoumissionRead,
    not_found="Soumission introuvable",
)


# --------------------------------------------------------------------------
# Projets de développement
# --------------------------------------------------------------------------

projects_router = _make_crud_router(
    prefix="/devlog/projects",
    model=DevlogProject,
    create_schema=DevlogProjectCreate,
    update_schema=DevlogProjectUpdate,
    read_schema=DevlogProjectRead,
    not_found="Projet introuvable",
)


# --------------------------------------------------------------------------
# Saisie d'heures
# --------------------------------------------------------------------------

time_entries_router = _make_crud_router(
    prefix="/devlog/time-entries",
    model=DevlogTimeEntry,
    create_schema=DevlogTimeEntryCreate,
    update_schema=DevlogTimeEntryUpdate,
    read_schema=DevlogTimeEntryRead,
    not_found="Saisie d'heures introuvable",
)


# --------------------------------------------------------------------------
# Facturation
# --------------------------------------------------------------------------

invoices_router = _make_crud_router(
    prefix="/devlog/invoices",
    model=DevlogInvoice,
    create_schema=DevlogInvoiceCreate,
    update_schema=DevlogInvoiceUpdate,
    read_schema=DevlogInvoiceRead,
    not_found="Facture introuvable",
)


# --------------------------------------------------------------------------
# Items de soumission (lignes)
# --------------------------------------------------------------------------

soumission_items_router = APIRouter(prefix="/devlog", tags=["devlog"])


def _compute_item_total(quantity: float, unit_price: float) -> float:
    return round(float(quantity or 0) * float(unit_price or 0), 2)


async def _refresh_soumission_amount(db, soumission_id: int) -> None:
    """Recalcule `DevlogSoumission.amount` à partir de ses items et le
    persiste — le total de la soumission est toujours la somme des items."""
    items = (
        await db.execute(
            select(DevlogSoumissionItem).where(
                DevlogSoumissionItem.soumission_id == soumission_id
            )
        )
    ).scalars().all()
    total = round(sum(float(it.total or 0) for it in items), 2)
    soumission = await GenericCrud(db, DevlogSoumission).get(soumission_id)
    if soumission is not None:
        soumission.amount = total
        await db.flush()


@soumission_items_router.get(
    "/soumissions/{soumission_id}/items",
    response_model=List[DevlogSoumissionItemRead],
)
async def list_soumission_items(
    soumission_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogSoumissionItem)
            .where(DevlogSoumissionItem.soumission_id == soumission_id)
            .order_by(DevlogSoumissionItem.position.asc(), DevlogSoumissionItem.id.asc())
        )
    ).scalars().all()
    return list(rows)


@soumission_items_router.post(
    "/soumission-items",
    response_model=DevlogSoumissionItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_soumission_item(
    data: DevlogSoumissionItemCreate, db: DBSession, _: CurrentUser
):
    if await GenericCrud(db, DevlogSoumission).get(data.soumission_id) is None:
        raise HTTPException(status_code=404, detail="Soumission introuvable")
    payload = data.model_dump(exclude_unset=True)
    payload["total"] = _compute_item_total(
        data.quantity, data.unit_price
    )
    obj = DevlogSoumissionItem(**payload)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await _refresh_soumission_amount(db, data.soumission_id)
    return DevlogSoumissionItemRead.model_validate(obj)


@soumission_items_router.patch(
    "/soumission-items/{item_id}",
    response_model=DevlogSoumissionItemRead,
)
async def update_soumission_item(
    item_id: int,
    data: DevlogSoumissionItemUpdate,
    db: DBSession,
    _: CurrentUser,
):
    crud = GenericCrud(db, DevlogSoumissionItem)
    obj = await crud.get(item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Item introuvable")
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(obj, field, value)
    obj.total = _compute_item_total(obj.quantity, obj.unit_price)
    await db.flush()
    await db.refresh(obj)
    await _refresh_soumission_amount(db, obj.soumission_id)
    return DevlogSoumissionItemRead.model_validate(obj)


@soumission_items_router.delete(
    "/soumission-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_soumission_item(
    item_id: int, db: DBSession, _: CurrentUser
):
    crud = GenericCrud(db, DevlogSoumissionItem)
    obj = await crud.get(item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Item introuvable")
    soumission_id = obj.soumission_id
    await crud.delete(obj)
    await _refresh_soumission_amount(db, soumission_id)


# --------------------------------------------------------------------------
# Vues « liées » — éléments rattachés à un lead / client / projet
# --------------------------------------------------------------------------

related_router = APIRouter(prefix="/devlog", tags=["devlog"])


@related_router.get(
    "/leads/{lead_id}/soumissions",
    response_model=List[DevlogSoumissionRead],
)
async def list_lead_soumissions(
    lead_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogSoumission)
            .where(DevlogSoumission.lead_id == lead_id)
            .order_by(DevlogSoumission.id.desc())
        )
    ).scalars().all()
    return list(rows)


@related_router.get(
    "/clients/{client_id}/soumissions",
    response_model=List[DevlogSoumissionRead],
)
async def list_client_soumissions(
    client_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogSoumission)
            .where(DevlogSoumission.client_id == client_id)
            .order_by(DevlogSoumission.id.desc())
        )
    ).scalars().all()
    return list(rows)


@related_router.get(
    "/clients/{client_id}/projects",
    response_model=List[DevlogProjectRead],
)
async def list_client_projects(
    client_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogProject)
            .where(DevlogProject.client_id == client_id)
            .order_by(DevlogProject.id.desc())
        )
    ).scalars().all()
    return list(rows)


@related_router.get(
    "/clients/{client_id}/invoices",
    response_model=List[DevlogInvoiceRead],
)
async def list_client_invoices(
    client_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogInvoice)
            .where(DevlogInvoice.client_id == client_id)
            .order_by(DevlogInvoice.id.desc())
        )
    ).scalars().all()
    return list(rows)


@related_router.get(
    "/projects/{project_id}/invoices",
    response_model=List[DevlogInvoiceRead],
)
async def list_project_invoices(
    project_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogInvoice)
            .where(DevlogInvoice.project_id == project_id)
            .order_by(DevlogInvoice.id.desc())
        )
    ).scalars().all()
    return list(rows)


@related_router.get(
    "/projects/{project_id}/time-entries",
    response_model=List[DevlogTimeEntryRead],
)
async def list_project_time_entries(
    project_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogTimeEntry)
            .where(DevlogTimeEntry.project_id == project_id)
            .order_by(DevlogTimeEntry.work_date.desc(), DevlogTimeEntry.id.desc())
        )
    ).scalars().all()
    return list(rows)
