"""Push an Achat to QuickBooks Online as a Bill or Purchase.

    POST /api/v1/achats/{id}/qbo/sync   — push manuel
    GET  /api/v1/achats/{id}/parts      — parts d'une facture QB fractionnée
    autopush_achat(achat_id)            — utilisé par les hooks auto

Le routage Bill vs Purchase est déterminé par achat.payment_method
(voir services/achat_qbo.py).

Note : l'envoi du PO par courriel a été déplacé vers
/api/v1/purchase-orders/{id}/send-po depuis la refonte PO/Achat.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DBSession
from app.models.achat import Achat
from app.services.permissions_service import user_has_capability
from app.services.achat_qbo import AchatSyncError, sync_achat_to_qbo


log = logging.getLogger(__name__)
router = APIRouter(prefix="/achats", tags=["achats-qbo"])


class AchatQboSyncResult(BaseModel):
    ok: bool
    qbo_bill_id: str
    qbo_doc_number: str
    qbo_vendor_id: str


@router.post(
    "/{achat_id}/qbo/sync",
    response_model=AchatQboSyncResult,
    summary="Push this achat to QuickBooks Online as a Bill or Purchase",
)
async def push_achat_to_qbo(
    achat_id: int, db: DBSession, user: CurrentUser
) -> AchatQboSyncResult:
    if not await user_has_capability(db, user, "qbo.push"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes pour cette action.",
        )
    try:
        result = await sync_achat_to_qbo(db, achat_id)
    except AchatSyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"QBO sync failed: {exc}",
        )
    return AchatQboSyncResult(**result)


async def autopush_achat(achat_id: int) -> None:
    """Auto-push silencieux — appelé par le hook qui détecte la
    transition status → received. Ouvre sa propre session DB. Si QBO
    n'est pas connecté ou que la sync rate, on log mais on n'échoue
    pas la requête utilisateur (qui a juste sauvegardé un statut).
    """
    from app.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await sync_achat_to_qbo(db, achat_id)
            await db.commit()
        log.info("Auto-push QBO achat %s ok", achat_id)
    except Exception as exc:
        log.warning(
            "Auto-push QBO achat %s a échoué (silencieux): %s",
            achat_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Facture QuickBooks FRACTIONNÉE : les parts Kratos d'une même transaction
# ---------------------------------------------------------------------------


class AchatPartRead(BaseModel):
    id: int
    project_id: Optional[int] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    amount_taxes: Optional[float] = None
    #: TTC de la part (amount + amount_taxes).
    total: float = 0.0
    status: str
    is_billable: bool = True
    payment_method: Optional[str] = None


class AchatPartsRead(BaseModel):
    """Parts Kratos d'une même transaction QuickBooks.

    Une facture fournisseur / dépense fractionnée dans QB entre plusieurs
    projets donne un achat PAR projet, qui partagent le même lien QB ;
    fractionnée entre un projet et une part hors projet, l'achat ne porte
    que la part du projet et ``reste_qb`` dit ce qui est resté dans QB."""

    qbo_id: Optional[str] = None
    qbo_doc_number: Optional[str] = None
    #: Total TTC de la transaction QB, quand l'import l'a noté.
    qbo_total: Optional[float] = None
    #: Somme TTC des parts présentes dans Kratos.
    total_kratos: float = 0.0
    #: Part de la transaction restée dans QB (hors projet), si connue.
    reste_qb: Optional[float] = None
    parts: list[AchatPartRead] = []


def _ttc(a: Achat) -> float:
    return round(float(a.amount or 0) + float(a.amount_taxes or 0), 2)


@router.get(
    "/{achat_id}/parts",
    response_model=AchatPartsRead,
    summary=(
        "Parts Kratos d'une facture QuickBooks fractionnée (achats qui "
        "partagent la même transaction QB) et part restée dans QB"
    ),
)
async def achat_parts(
    achat_id: int, db: DBSession, _: CurrentUser
) -> AchatPartsRead:
    ach = await db.get(Achat, achat_id)
    if ach is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achat not found")
    # Un achat poussé depuis Kratos garde l'Id QB dans qbo_bill_id (Bill
    # OU Purchase) ; un achat importé par le pull des coûts le garde dans
    # qbo_purchase_id → on cherche sur les deux colonnes.
    qids = {str(q) for q in (ach.qbo_bill_id, ach.qbo_purchase_id) if q}
    if qids:
        rows = list(
            (
                await db.execute(
                    select(Achat)
                    .where(
                        or_(
                            Achat.qbo_bill_id.in_(qids),
                            Achat.qbo_purchase_id.in_(qids),
                        )
                    )
                    .order_by(Achat.id)
                )
            ).scalars().all()
        )
    else:
        rows = [ach]
    parts = [
        AchatPartRead(
            id=a.id,
            project_id=a.project_id,
            description=a.description,
            amount=float(a.amount) if a.amount is not None else None,
            amount_taxes=(
                float(a.amount_taxes) if a.amount_taxes is not None else None
            ),
            total=_ttc(a),
            status=a.status,
            is_billable=bool(a.is_billable),
            payment_method=a.payment_method,
        )
        for a in rows
    ]
    total_kratos = round(sum(p.total for p in parts), 2)
    totaux_qb = [
        float(a.qbo_txn_total) for a in rows if a.qbo_txn_total is not None
    ]
    qbo_total = round(max(totaux_qb), 2) if totaux_qb else None
    reste = (
        round(qbo_total - total_kratos, 2)
        if qbo_total is not None and qbo_total - total_kratos > 0.01
        else None
    )
    return AchatPartsRead(
        qbo_id=next(iter(sorted(qids)), None),
        qbo_doc_number=ach.qbo_doc_number,
        qbo_total=qbo_total,
        total_kratos=total_kratos,
        reste_qb=reste,
        parts=parts,
    )
