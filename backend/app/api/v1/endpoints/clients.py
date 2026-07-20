"""
Client endpoints.

CRUD operations for clients with role-based access control.
"""

from typing import List

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentAdmin, DBSession, RequireManager
from app.schemas.client import (
    ClientCreate,
    ClientRead,
    ClientReadWithProjects,
    ClientUpdate,
)
from app.services.client import ClientService


router = APIRouter(prefix="/clients", tags=["clients"])


@router.post(
    "",
    response_model=ClientRead,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un client (gestionnaire+)",
)
async def create_client(
    data: ClientCreate,
    db: DBSession,
    current_user: RequireManager,
) -> ClientRead:
    """Crée un client. Gestionnaire+ — la page Clients leur est ouverte
    (registre : construction.clients = manager), or créer exigeait admin
    (retour Phil 2026-07-20 : Olivier bloqué par « Admin privileges
    required »)."""
    service = ClientService(db)
    client = await service.create(data)
    # Synchro QBO auto (inerte tant que l'interrupteur est OFF).
    import asyncio

    from app.services.qbo_auto_sync import autopush_client

    asyncio.create_task(autopush_client(int(client.id)))
    return ClientRead.model_validate(client)


@router.get(
    "",
    response_model=List[ClientRead],
    summary="List all clients",
)
async def list_clients(
    db: DBSession,
    current_user: RequireManager,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> List[ClientRead]:
    """List all clients. Requires authentication."""
    service = ClientService(db)
    clients = await service.list(skip=skip, limit=limit)
    return [ClientRead.model_validate(c) for c in clients]


@router.get(
    "/{client_id}",
    response_model=ClientReadWithProjects,
    summary="Get a client by ID",
)
async def get_client(
    client_id: int,
    db: DBSession,
    current_user: RequireManager,
) -> ClientReadWithProjects:
    """Get a client with its projects. Requires authentication."""
    service = ClientService(db)
    client = await service.get_by_id(client_id, with_projects=True)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )
    return ClientReadWithProjects.model_validate(client)


@router.put(
    "/{client_id}",
    response_model=ClientRead,
    summary="Modifier un client (gestionnaire+)",
)
async def update_client(
    client_id: int,
    data: ClientUpdate,
    db: DBSession,
    current_user: RequireManager,
) -> ClientRead:
    """Modifie un client. Gestionnaire+ (même logique que la création)."""
    service = ClientService(db)
    client = await service.update(client_id, data)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )
    return ClientRead.model_validate(client)


@router.delete(
    "/{client_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un client (admin)",
)
async def delete_client(
    client_id: int,
    db: DBSession,
    current_admin: CurrentAdmin,
) -> None:
    """Supprime un client ET ses projets — reste réservé aux admins
    (action destructive en cascade)."""
    service = ClientService(db)
    deleted = await service.delete(client_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )
