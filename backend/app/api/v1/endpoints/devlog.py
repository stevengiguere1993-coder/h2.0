"""Endpoints — pôle Développement logiciel.

Deux ressources :
  * /api/v1/devlog/clients — clients du pôle (boîtes pour qui on
    développe des plateformes / logiciels) ;
  * /api/v1/devlog/leads — pipeline kanban du closer.

Accessible à tout utilisateur authentifié : nouveau pôle interne,
petite équipe (closer / PM / devs partagent l'outil).
"""

from typing import List

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.devlog_client import DevlogClient
from app.models.devlog_lead import LEAD_STATUSES, DevlogLead
from app.repositories.generic import GenericCrud
from app.schemas.devlog import (
    DevlogClientCreate,
    DevlogClientRead,
    DevlogClientUpdate,
    DevlogLeadCreate,
    DevlogLeadRead,
    DevlogLeadStatusUpdate,
    DevlogLeadUpdate,
)

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
