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
from app.models.devlog_contract import DevlogContract
from app.models.devlog_invoice import DevlogInvoice
from app.models.devlog_invoice_item import DevlogInvoiceItem
from app.models.devlog_lead import LEAD_STATUSES, DevlogLead
from app.models.devlog_project import DevlogProject
from app.models.devlog_soumission import DevlogSoumission
from app.models.devlog_soumission_item import DevlogSoumissionItem
from app.models.devlog_sous_traitant import DevlogSousTraitant
from app.models.devlog_time_entry import DevlogTimeEntry
from app.repositories.generic import GenericCrud
from app.schemas.devlog import (
    DevlogClientCreate,
    DevlogClientRead,
    DevlogClientUpdate,
    DevlogContractCreate,
    DevlogContractPublicRead,
    DevlogContractRead,
    DevlogContractSignRequest,
    DevlogContractUpdate,
    DevlogInvoiceCreate,
    DevlogInvoiceImportRequest,
    DevlogInvoiceImportResult,
    DevlogInvoiceItemCreate,
    DevlogInvoiceItemRead,
    DevlogInvoiceItemUpdate,
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
    DevlogSousTraitantCreate,
    DevlogSousTraitantRead,
    DevlogSousTraitantUpdate,
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
# Sous-traitants
# --------------------------------------------------------------------------

sous_traitants_router = _make_crud_router(
    prefix="/devlog/sous-traitants",
    model=DevlogSousTraitant,
    create_schema=DevlogSousTraitantCreate,
    update_schema=DevlogSousTraitantUpdate,
    read_schema=DevlogSousTraitantRead,
    not_found="Sous-traitant introuvable",
)


# --------------------------------------------------------------------------
# Items de facture + import depuis projet
# --------------------------------------------------------------------------

invoice_items_router = APIRouter(prefix="/devlog", tags=["devlog"])


async def _refresh_invoice_amount(db, invoice_id: int) -> None:
    items = (
        await db.execute(
            select(DevlogInvoiceItem).where(
                DevlogInvoiceItem.invoice_id == invoice_id
            )
        )
    ).scalars().all()
    total = round(sum(float(it.total or 0) for it in items), 2)
    inv = await GenericCrud(db, DevlogInvoice).get(invoice_id)
    if inv is not None:
        inv.amount = total
        await db.flush()


@invoice_items_router.get(
    "/invoices/{invoice_id}/items",
    response_model=List[DevlogInvoiceItemRead],
)
async def list_invoice_items(
    invoice_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogInvoiceItem)
            .where(DevlogInvoiceItem.invoice_id == invoice_id)
            .order_by(DevlogInvoiceItem.position.asc(), DevlogInvoiceItem.id.asc())
        )
    ).scalars().all()
    return list(rows)


@invoice_items_router.post(
    "/invoice-items",
    response_model=DevlogInvoiceItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_invoice_item(
    data: DevlogInvoiceItemCreate, db: DBSession, _: CurrentUser
):
    if await GenericCrud(db, DevlogInvoice).get(data.invoice_id) is None:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    payload = data.model_dump(exclude_unset=True)
    payload["total"] = _compute_item_total(data.quantity, data.unit_price)
    obj = DevlogInvoiceItem(**payload)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await _refresh_invoice_amount(db, data.invoice_id)
    return DevlogInvoiceItemRead.model_validate(obj)


@invoice_items_router.patch(
    "/invoice-items/{item_id}",
    response_model=DevlogInvoiceItemRead,
)
async def update_invoice_item(
    item_id: int,
    data: DevlogInvoiceItemUpdate,
    db: DBSession,
    _: CurrentUser,
):
    crud = GenericCrud(db, DevlogInvoiceItem)
    obj = await crud.get(item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Item introuvable")
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(obj, field, value)
    obj.total = _compute_item_total(obj.quantity, obj.unit_price)
    await db.flush()
    await db.refresh(obj)
    await _refresh_invoice_amount(db, obj.invoice_id)
    return DevlogInvoiceItemRead.model_validate(obj)


@invoice_items_router.delete(
    "/invoice-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_invoice_item(
    item_id: int, db: DBSession, _: CurrentUser
):
    crud = GenericCrud(db, DevlogInvoiceItem)
    obj = await crud.get(item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Item introuvable")
    invoice_id = obj.invoice_id
    await crud.delete(obj)
    await _refresh_invoice_amount(db, invoice_id)


@invoice_items_router.post(
    "/invoices/{invoice_id}/import-sources",
    response_model=DevlogInvoiceImportResult,
)
async def import_into_invoice(
    invoice_id: int,
    data: DevlogInvoiceImportRequest,
    db: DBSession,
    _: CurrentUser,
):
    """Ajoute des lignes à la facture en important depuis un projet :
    heures totales + (optionnel) items de la soumission acceptée. Pas
    de markup automatique pour l'instant — le `hourly_rate` du body
    est le tarif facturable que l'admin choisit pour ce batch."""
    inv = await GenericCrud(db, DevlogInvoice).get(invoice_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Facture introuvable")

    existing = (
        await db.execute(
            select(DevlogInvoiceItem.position).where(
                DevlogInvoiceItem.invoice_id == invoice_id
            )
        )
    ).scalars().all()
    next_pos = (max(existing) + 1) if existing else 0
    added = 0

    if data.include_hours:
        rows = (
            await db.execute(
                select(DevlogTimeEntry).where(
                    DevlogTimeEntry.project_id == data.project_id
                )
            )
        ).scalars().all()
        total_hours = round(sum(float(r.hours or 0) for r in rows), 2)
        if total_hours > 0:
            rate = float(data.hourly_rate or 0)
            db.add(
                DevlogInvoiceItem(
                    invoice_id=invoice_id,
                    position=next_pos,
                    description=f"Heures du projet #{data.project_id}",
                    unit="h",
                    quantity=total_hours,
                    unit_price=rate,
                    total=round(total_hours * rate, 2),
                    source_kind="heures",
                )
            )
            next_pos += 1
            added += 1

    if data.include_soumission and data.soumission_id:
        items = (
            await db.execute(
                select(DevlogSoumissionItem)
                .where(DevlogSoumissionItem.soumission_id == data.soumission_id)
                .order_by(DevlogSoumissionItem.position.asc())
            )
        ).scalars().all()
        for it in items:
            db.add(
                DevlogInvoiceItem(
                    invoice_id=invoice_id,
                    position=next_pos,
                    description=it.description,
                    unit=it.unit,
                    quantity=it.quantity,
                    unit_price=it.unit_price,
                    total=it.total,
                    source_kind="soumission",
                )
            )
            next_pos += 1
            added += 1

    await db.flush()
    await _refresh_invoice_amount(db, invoice_id)
    return DevlogInvoiceImportResult(added=added)


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


# --------------------------------------------------------------------------
# Contrats électroniques (signature publique avec token)
# --------------------------------------------------------------------------

import secrets
from datetime import datetime, timezone
from fastapi import Request

contracts_router = APIRouter(prefix="/devlog", tags=["devlog"])


def _gen_token() -> str:
    return secrets.token_urlsafe(32)


@contracts_router.get(
    "/contracts",
    response_model=List[DevlogContractRead],
)
async def list_contracts(db: DBSession, _: CurrentUser):
    rows = (
        await db.execute(
            select(DevlogContract).order_by(DevlogContract.id.desc())
        )
    ).scalars().all()
    return list(rows)


@contracts_router.post(
    "/contracts",
    response_model=DevlogContractRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract(
    data: DevlogContractCreate, db: DBSession, _: CurrentUser
):
    obj = await GenericCrud(db, DevlogContract).create(data)
    return DevlogContractRead.model_validate(obj)


@contracts_router.get(
    "/contracts/{contract_id}",
    response_model=DevlogContractRead,
)
async def get_contract(contract_id: int, db: DBSession, _: CurrentUser):
    obj = await GenericCrud(db, DevlogContract).get(contract_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    return DevlogContractRead.model_validate(obj)


@contracts_router.patch(
    "/contracts/{contract_id}",
    response_model=DevlogContractRead,
)
async def update_contract(
    contract_id: int,
    data: DevlogContractUpdate,
    db: DBSession,
    _: CurrentUser,
):
    crud = GenericCrud(db, DevlogContract)
    obj = await crud.get(contract_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    if obj.status == "signe":
        raise HTTPException(
            status_code=400,
            detail="Contrat signé — édition verrouillée.",
        )
    obj = await crud.update(obj, data)
    return DevlogContractRead.model_validate(obj)


@contracts_router.delete(
    "/contracts/{contract_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_contract(
    contract_id: int, db: DBSession, _: CurrentUser
):
    crud = GenericCrud(db, DevlogContract)
    obj = await crud.get(contract_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    await crud.delete(obj)


@contracts_router.post(
    "/contracts/{contract_id}/send",
    response_model=DevlogContractRead,
    summary=(
        "Génère un signature_token (si absent) et passe le contrat en "
        "« envoye ». L'admin peut copier le lien public et l'envoyer."
    ),
)
async def send_contract(
    contract_id: int, db: DBSession, _: CurrentUser
):
    obj = await GenericCrud(db, DevlogContract).get(contract_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    if not obj.signature_token:
        obj.signature_token = _gen_token()
    obj.status = "envoye"
    obj.sent_at = datetime.now(timezone.utc)
    await db.flush()
    return DevlogContractRead.model_validate(obj)


# --- Endpoints publics (sans auth — accédés par lien token) ---

public_contracts_router = APIRouter(
    prefix="/public/devlog", tags=["devlog-public"]
)


@public_contracts_router.get(
    "/contracts/{token}",
    response_model=DevlogContractPublicRead,
)
async def public_get_contract(token: str, db: DBSession):
    obj = (
        await db.execute(
            select(DevlogContract).where(
                DevlogContract.signature_token == token
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Lien invalide")
    return DevlogContractPublicRead.model_validate(obj)


@public_contracts_router.post(
    "/contracts/{token}/sign",
    response_model=DevlogContractPublicRead,
)
async def public_sign_contract(
    token: str,
    data: DevlogContractSignRequest,
    request: Request,
    db: DBSession,
):
    obj = (
        await db.execute(
            select(DevlogContract).where(
                DevlogContract.signature_token == token
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Lien invalide")
    if obj.status == "signe":
        # Idempotent : on retourne la version signée sans réécrire.
        return DevlogContractPublicRead.model_validate(obj)
    if obj.status == "annule":
        raise HTTPException(
            status_code=400, detail="Contrat annulé — signature refusée."
        )
    obj.status = "signe"
    obj.signed_at = datetime.now(timezone.utc)
    obj.signed_name = data.name.strip()[:255]
    # Best-effort IP capture.
    fwd = request.headers.get("x-forwarded-for") or ""
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")
    obj.signed_ip = (ip or "")[:64]
    await db.flush()
    return DevlogContractPublicRead.model_validate(obj)
