"""Endpoints d'action sur un PurchaseOrder (envoi par courriel +
conversion en Achat). Le CRUD basique du PO est géré par le router
générique `purchase_orders_router` dans business.py.

    POST /api/v1/purchase-orders/{id}/send-po
    POST /api/v1/purchase-orders/{id}/convert-to-achat
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.achat import Achat, AchatStatus
from app.models.employe import Employe
from app.models.fournisseur import Fournisseur
from app.models.project import Project
from app.models.purchase_order import PurchaseOrder, PurchaseOrderStatus
from app.models.purchase_order_item import PurchaseOrderItem
from app.schemas.business import AchatRead, PurchaseOrderRead
from app.services.purchase_order_send import (
    PurchaseOrderSendError,
    send_purchase_order,
)


log = logging.getLogger(__name__)
router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])


# --------------------------------------------------------------------------
# Lecture mobile (app terrain du staff). Contrairement au CRUD générique
# des PO (réservé aux managers), ces routes sont ouvertes à tout employé
# connecté : un homme à tout faire assigné doit pouvoir consulter son bon
# de commande sur son téléphone (quoi acheter, où, montant max). On ne
# renvoie QUE les libellés utiles (fournisseur / projet / assigné) — jamais
# les taux horaires ni les infos comptables des fiches employé/fournisseur.
# --------------------------------------------------------------------------


class MobilePOLine(BaseModel):
    id: int
    position: int
    description: str
    unit: Optional[str] = None
    quantity: float
    unit_price: float
    total: float


class MobilePOItem(BaseModel):
    id: int
    reference: str
    status: str
    amount_max: Optional[float] = None
    payment_method: Optional[str] = None
    description: Optional[str] = None
    fournisseur_name: Optional[str] = None
    project_name: Optional[str] = None
    assigned_name: Optional[str] = None
    is_mine: bool = False
    created_at: datetime


class MobilePODetail(MobilePOItem):
    project_address: Optional[str] = None
    notes: Optional[str] = None
    sent_at: Optional[datetime] = None
    items: list[MobilePOLine] = Field(default_factory=list)


def _my_employe_ids(employes: list[Employe], user_email: Optional[str]) -> set:
    """Ids des fiches employé dont le courriel = celui de l'utilisateur."""
    email = (user_email or "").strip().lower()
    if not email:
        return set()
    return {
        e.id
        for e in employes
        if (e.email or "").strip().lower() == email
    }


@router.get(
    "/mobile/list",
    response_model=list[MobilePOItem],
    summary="Liste des PO pour l'app mobile (libellés résolus, tout staff)",
)
async def mobile_po_list(
    db: DBSession,
    current_user: CurrentUser,
    limit: int = 300,
) -> list[MobilePOItem]:
    pos = (
        await db.execute(
            select(PurchaseOrder)
            .order_by(PurchaseOrder.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    ).scalars().all()

    fr_ids = {p.fournisseur_id for p in pos if p.fournisseur_id}
    pr_ids = {p.project_id for p in pos if p.project_id}

    fr_names: dict = {}
    if fr_ids:
        rows = (
            await db.execute(
                select(Fournisseur.id, Fournisseur.name).where(
                    Fournisseur.id.in_(fr_ids)
                )
            )
        ).all()
        fr_names = {r[0]: r[1] for r in rows}

    pr_names: dict = {}
    if pr_ids:
        rows = (
            await db.execute(
                select(Project.id, Project.name).where(Project.id.in_(pr_ids))
            )
        ).all()
        pr_names = {r[0]: r[1] for r in rows}

    employes = (await db.execute(select(Employe))).scalars().all()
    emp_names = {e.id: e.full_name for e in employes}
    mine = _my_employe_ids(employes, getattr(current_user, "email", None))

    return [
        MobilePOItem(
            id=p.id,
            reference=p.reference,
            status=p.status,
            amount_max=(
                float(p.amount_max) if p.amount_max is not None else None
            ),
            payment_method=p.payment_method,
            description=p.description,
            fournisseur_name=fr_names.get(p.fournisseur_id),
            project_name=pr_names.get(p.project_id),
            assigned_name=emp_names.get(p.assigned_employe_id),
            is_mine=(
                p.assigned_employe_id is not None
                and p.assigned_employe_id in mine
            ),
            created_at=p.created_at,
        )
        for p in pos
    ]


@router.get(
    "/mobile/{po_id}",
    response_model=MobilePODetail,
    summary="Détail d'un PO pour l'app mobile (avec articles, tout staff)",
)
async def mobile_po_detail(
    po_id: int,
    db: DBSession,
    current_user: CurrentUser,
) -> MobilePODetail:
    po = (
        await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
    ).scalar_one_or_none()
    if po is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PO introuvable")

    fr_name = None
    if po.fournisseur_id:
        fr_name = (
            await db.execute(
                select(Fournisseur.name).where(
                    Fournisseur.id == po.fournisseur_id
                )
            )
        ).scalar_one_or_none()

    pr_name = None
    pr_address = None
    if po.project_id:
        row = (
            await db.execute(
                select(Project.name, Project.address).where(
                    Project.id == po.project_id
                )
            )
        ).first()
        if row is not None:
            pr_name, pr_address = row[0], row[1]

    assigned_name = None
    is_mine = False
    if po.assigned_employe_id:
        emp = (
            await db.execute(
                select(Employe).where(Employe.id == po.assigned_employe_id)
            )
        ).scalar_one_or_none()
        if emp is not None:
            assigned_name = emp.full_name
            user_email = (getattr(current_user, "email", "") or "").strip().lower()
            is_mine = bool(
                user_email
                and (emp.email or "").strip().lower() == user_email
            )

    lines = (
        await db.execute(
            select(PurchaseOrderItem)
            .where(PurchaseOrderItem.purchase_order_id == po.id)
            .order_by(
                PurchaseOrderItem.position.asc(),
                PurchaseOrderItem.id.asc(),
            )
        )
    ).scalars().all()

    return MobilePODetail(
        id=po.id,
        reference=po.reference,
        status=po.status,
        amount_max=(float(po.amount_max) if po.amount_max is not None else None),
        payment_method=po.payment_method,
        description=po.description,
        fournisseur_name=fr_name,
        project_name=pr_name,
        project_address=pr_address,
        assigned_name=assigned_name,
        is_mine=is_mine,
        notes=po.notes,
        sent_at=po.sent_at,
        created_at=po.created_at,
        items=[
            MobilePOLine(
                id=it.id,
                position=it.position,
                description=it.description,
                unit=it.unit,
                quantity=float(it.quantity),
                unit_price=float(it.unit_price),
                total=float(it.total),
            )
            for it in lines
        ],
    )


class SendPoRequest(BaseModel):
    extra_message: Optional[str] = Field(default=None, max_length=2000)


@router.post(
    "/{po_id}/send-po",
    response_model=PurchaseOrderRead,
    summary="Envoyer le PO par courriel à l'employé assigné",
)
async def send_po_endpoint(
    po_id: int,
    data: SendPoRequest,
    db: DBSession,
    _: CurrentUser,
) -> PurchaseOrderRead:
    try:
        po = await send_purchase_order(
            db, po_id, extra_message=data.extra_message
        )
    except PurchaseOrderSendError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return PurchaseOrderRead.model_validate(po)


class ConvertToAchatRequest(BaseModel):
    """Champs réels au moment où l'employé revient avec sa facture
    fournisseur. Tous optionnels — ce qui n'est pas fourni est repris
    du PO source."""

    amount: Optional[float] = Field(default=None, ge=0)
    supplier_invoice_number: Optional[str] = Field(default=None, max_length=64)
    invoice_date: Optional[str] = None  # ISO date string
    payment_method: Optional[str] = Field(default=None, max_length=32)
    description: Optional[str] = None
    notes: Optional[str] = None


@router.post(
    "/{po_id}/convert-to-achat",
    response_model=AchatRead,
    summary="Créer un Achat à partir de ce PO",
)
async def convert_po_to_achat(
    po_id: int,
    data: ConvertToAchatRequest,
    db: DBSession,
    _: CurrentUser,
    background: BackgroundTasks,
    defer_sync: bool = False,
) -> AchatRead:
    """Crée un Achat (transaction comptable) lié à ce PO. Pré-remplit
    fournisseur, projet et mode de paiement depuis le PO ; l'utilisateur
    n'a qu'à fournir le montant réel + le # de facture fournisseur.

    Marque le PO comme `fulfilled` et crée l'Achat en statut `received`.
    L'auto-push QBO démarre en arrière-plan (selon le mode de paiement).

    `defer_sync=true` saute le push automatique pour permettre au client
    d'uploader la facture en pièce jointe AVANT de pousser dans QB. Le
    client doit ensuite appeler POST /achats/{id}/qbo/sync.
    """

    po = (
        await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
    ).scalar_one_or_none()
    if po is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PO introuvable")
    if po.status == PurchaseOrderStatus.CANCELLED.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Ce PO est annulé — recrée un nouveau PO si besoin.",
        )

    invoice_dt = None
    if data.invoice_date:
        try:
            from datetime import date as _date

            invoice_dt = _date.fromisoformat(data.invoice_date[:10])
        except Exception:
            invoice_dt = None

    # Description : si l'utilisateur n'a rien fourni, on essaie de
    # concaténer les articles du PO (« 70 tubes caulking · 2 boîtes
    # de vis 2 1/2 · ... »). Sinon fallback sur la description du PO.
    description = data.description
    if not description:
        from app.models.purchase_order_item import PurchaseOrderItem

        items = (
            await db.execute(
                select(PurchaseOrderItem)
                .where(PurchaseOrderItem.purchase_order_id == po.id)
                .order_by(
                    PurchaseOrderItem.position.asc(),
                    PurchaseOrderItem.id.asc(),
                )
            )
        ).scalars().all()
        if items:
            parts = []
            for it in items:
                qty_int = (
                    int(it.quantity)
                    if float(it.quantity).is_integer()
                    else float(it.quantity)
                )
                qty_str = f"{qty_int}"
                if it.unit:
                    qty_str = f"{qty_str} {it.unit}"
                parts.append(f"{qty_str} × {it.description}")
            description = " · ".join(parts)
        else:
            description = po.description

    achat = Achat(
        purchase_order_id=po.id,
        fournisseur_id=po.fournisseur_id,
        project_id=po.project_id,
        description=description,
        amount=(data.amount if data.amount is not None else po.amount_max),
        supplier_invoice_number=data.supplier_invoice_number,
        invoice_date=invoice_dt,
        payment_method=(data.payment_method or po.payment_method),
        status=AchatStatus.RECEIVED.value,
        received_at=datetime.now(timezone.utc),
        notes=data.notes,
    )
    db.add(achat)
    await db.flush()
    await db.refresh(achat)

    # Marque le PO comme accompli (un Achat l'a consommé). Reste
    # cliquable pour consulter, mais visuellement « terminé ».
    po.status = PurchaseOrderStatus.FULFILLED.value
    await db.flush()

    # Auto-push vers QBO en arrière-plan, sauf si on diffère pour
    # permettre l'upload d'une pièce jointe avant le push.
    # On passe par BackgroundTasks (dépendance injectée) plutôt qu'un
    # asyncio.create_task : la tâche détachée n'était référencée nulle
    # part et pouvait être ramassée par le GC avant de s'exécuter.
    # BackgroundTasks garantit l'exécution après l'envoi de la réponse.
    if not defer_sync:
        try:
            from app.api.v1.endpoints.achat_qbo import autopush_achat

            background.add_task(autopush_achat, int(achat.id))
        except Exception as exc:
            log.warning("Auto-push QBO planning échoué: %s", exc)

    return AchatRead.model_validate(achat)
