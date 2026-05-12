"""Generic CRUD endpoints for business entities.

All endpoints require an authenticated user.
"""

from typing import List, Type

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.db.base import Base
from app.models.achat import Achat
from app.models.agenda_event import AgendaEvent
from app.models.bon_travail import BonTravail
from app.models.employe import Employe
from app.models.facture import Facture
from app.models.fournisseur import Fournisseur
from app.models.punch import Punch
from app.models.purchase_order import PurchaseOrder
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
    PurchaseOrderCreate,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
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
    require_manager: bool = True,
) -> APIRouter:
    """Generic CRUD endpoints. By default they require manager+ role so
    that plain employees don't see (or modify) records they shouldn't.
    Set ``require_manager=False`` to keep them open to any logged-in
    user (e.g. agenda events which employees need to read)."""
    router = APIRouter(prefix=prefix, tags=[tag])

    # One auth dep per-operation: manager+ for writes always, reads when
    # require_manager=True. For open routers (agenda), reads are any user
    # but writes still require manager+.
    AuthRead = RequireManager if require_manager else CurrentUser
    AuthWrite = RequireManager

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create(data: create_schema, db: DBSession, _: AuthWrite):  # type: ignore[valid-type]
        # Numérotation séquentielle auto pour Soumission / Facture si
        # la référence n'est pas fournie (alignée sur la séquence
        # QuickBooks via /api/v1/settings/numbering).
        if hasattr(data, "reference") and getattr(data, "reference", None) in (
            None,
            "",
        ):
            from app.services.numbering import (
                next_facture_number,
                next_po_number,
                next_soumission_number,
            )

            if model is Soumission:
                data.reference = await next_soumission_number(db)
            elif model is Facture:
                data.reference = await next_facture_number(db)
            elif model is PurchaseOrder:
                data.reference = await next_po_number(db)
        crud = GenericCrud(db, model)
        obj = await crud.create(data)
        # Auto-push QBO pour tout Achat créé en statut « received »
        # (cas usuel : facture fournisseur saisie en différé).
        if model is Achat and getattr(obj, "status", None) == "received":
            import asyncio

            from app.api.v1.endpoints.achat_qbo import autopush_achat

            asyncio.create_task(autopush_achat(int(obj.id)))
        # Auto-bump : tout Punch créé sur un projet bascule celui-ci
        # en « En cours » s'il ne l'est pas déjà.
        if model is Punch:
            from app.services.project_auto_status import (
                bump_to_in_progress_if_needed,
            )

            await bump_to_in_progress_if_needed(
                db, getattr(obj, "project_id", None)
            )
            await db.flush()
        return read_schema.model_validate(obj)

    @router.get("", response_model=List[read_schema])  # type: ignore[valid-type]
    async def list_items(
        db: DBSession,
        _: AuthRead,
        skip: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
    ):
        crud = GenericCrud(db, model)
        items = await crud.list(skip=skip, limit=limit)
        return [read_schema.model_validate(i) for i in items]

    @router.get("/{item_id}")
    async def get_item(item_id: int, db: DBSession, _: AuthRead):
        crud = GenericCrud(db, model)
        obj = await crud.get(item_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        return read_schema.model_validate(obj)

    @router.patch("/{item_id}")
    async def update_item(item_id: int, data: update_schema, db: DBSession, _: AuthWrite):  # type: ignore[valid-type]
        crud = GenericCrud(db, model)
        obj = await crud.get(item_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        # Capture pre-update status pour détecter la transition
        # vers received sur les achats → autopush QBO en background.
        prev_status = (
            getattr(obj, "status", None) if model is Achat else None
        )
        # Capture pre-update project_id du Punch — si on rattache un
        # punch existant à un projet (ou on le change de projet), on
        # bumpera aussi ce projet.
        prev_project_id = (
            getattr(obj, "project_id", None) if model is Punch else None
        )
        obj = await crud.update(obj, data)
        if model is Achat:
            new_status = getattr(obj, "status", None)
            if prev_status != "received" and new_status == "received":
                import asyncio

                from app.api.v1.endpoints.achat_qbo import autopush_achat

                asyncio.create_task(autopush_achat(int(obj.id)))
        if model is Punch:
            new_project_id = getattr(obj, "project_id", None)
            if new_project_id is not None and new_project_id != prev_project_id:
                from app.services.project_auto_status import (
                    bump_to_in_progress_if_needed,
                )

                await bump_to_in_progress_if_needed(db, new_project_id)
                await db.flush()
        return read_schema.model_validate(obj)

    @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_item(item_id: int, db: DBSession, _: AuthWrite):
        crud = GenericCrud(db, model)
        obj = await crud.get(item_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        await crud.delete(obj)
        # Après suppression d'un PO, on recycle son numéro : on
        # ré-aligne le compteur `next_po_number` sur (max restant + 1).
        # Comme ça, supprimer le dernier PO-0030 fait que le prochain
        # créé reprendra le numéro 0030.
        if model is PurchaseOrder:
            from app.services.numbering import resync_po_counter

            await resync_po_counter(db)

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
    # Agenda reads must stay open to employees (they need to consult
    # their own schedule). Writes still require manager+.
    prefix="/agenda", tag="agenda",
    model=AgendaEvent, create_schema=AgendaEventCreate, update_schema=AgendaEventUpdate, read_schema=AgendaEventRead,
    require_manager=False,
)
bons_router = make_crud_router(
    prefix="/bons-travail", tag="bons-travail",
    model=BonTravail, create_schema=BonTravailCreate, update_schema=BonTravailUpdate, read_schema=BonTravailRead,
)
punch_router = make_crud_router(
    # Reads stay open: employees consult their own punches via
    # /punch/me. Writes (admin edits) still require manager+.
    prefix="/punch", tag="punch",
    model=Punch, create_schema=PunchCreate, update_schema=PunchUpdate, read_schema=PunchRead,
    require_manager=False,
)
factures_router = make_crud_router(
    prefix="/factures", tag="factures",
    model=Facture, create_schema=FactureCreate, update_schema=FactureUpdate, read_schema=FactureRead,
)
achats_router = make_crud_router(
    prefix="/achats", tag="achats",
    model=Achat, create_schema=AchatCreate, update_schema=AchatUpdate, read_schema=AchatRead,
)
purchase_orders_router = make_crud_router(
    prefix="/purchase-orders", tag="purchase-orders",
    model=PurchaseOrder,
    create_schema=PurchaseOrderCreate,
    update_schema=PurchaseOrderUpdate,
    read_schema=PurchaseOrderRead,
)
