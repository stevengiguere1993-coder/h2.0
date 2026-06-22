"""Achat — actions de paiement.

    POST /api/v1/achats/{id}/mark-paid    — bouton « Marquer paye »
    POST /api/v1/achats/sync-from-qbo     — pull QB Bills -> Kratos

Quand un achat etait facture fournisseur (bill_to_pay) et qu'on le
paye finalement, on enregistre le mode reel + la date. Le statut
passe a `paid` et l'echeance disparait.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import DBSession, RequireManager
from app.models.achat import Achat, AchatStatus, PaymentMethod
from app.services.achat_payment import mark_achat_paid
from app.services.achat_qbo_pull import QboPullError, pull_new_bills_from_qbo


router = APIRouter(prefix="/achats", tags=["achats-payment"])


_ALLOWED_METHODS = {m.value for m in PaymentMethod}


class MarkPaidPayload(BaseModel):
    payment_method: str = Field(..., max_length=32)
    paid_at: Optional[datetime] = None


class AchatPaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    payment_method: Optional[str]
    paid_at: Optional[datetime]
    due_at: Optional[datetime] = None


@router.post(
    "/{achat_id}/mark-paid",
    response_model=AchatPaymentRead,
    summary="Marquer un achat comme paye (set status, paid_at, methode)",
)
async def mark_paid(
    achat_id: int,
    payload: MarkPaidPayload,
    db: DBSession,
    _: RequireManager,
) -> AchatPaymentRead:
    if payload.payment_method not in _ALLOWED_METHODS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Mode de paiement invalide : {payload.payment_method}",
        )
    if payload.payment_method == PaymentMethod.BILL_TO_PAY.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Pour marquer paye, choisis le mode reel de paiement "
            "(cheque, carte) — pas 'facture a payer'.",
        )
    achat = await db.get(Achat, achat_id)
    if achat is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Achat introuvable."
        )
    if achat.status == AchatStatus.CANCELLED.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cet achat est annule.",
        )
    await mark_achat_paid(
        db,
        achat,
        payment_method=payload.payment_method,
        paid_at=payload.paid_at,
    )
    await db.flush()

    # Sync vers QB en background : si l'Achat a un qbo_bill_id, on
    # cree la BillPayment correspondante pour que le Bill QB passe
    # aussi en paye cote comptable. Fire-and-forget : on n'attend pas
    # la reponse QB pour repondre au frontend (la modal reste rapide).
    # Fail-closed : inerte tant que l'interrupteur QBO auto-sync est OFF
    # (cohérent avec factures/devis ; évite de pousser pendant la
    # migration de masse).
    if achat.qbo_bill_id:
        import asyncio

        from app.db.session import AsyncSessionLocal
        from app.services.achat_qbo import push_bill_payment_to_qbo
        from app.services.qbo_auto_sync import is_qbo_auto_sync_enabled

        async def _push_async(achat_id: int) -> None:
            if not await is_qbo_auto_sync_enabled():
                return
            async with AsyncSessionLocal() as fresh_db:
                try:
                    await push_bill_payment_to_qbo(fresh_db, achat_id)
                    await fresh_db.commit()
                except Exception:
                    await fresh_db.rollback()

        asyncio.create_task(_push_async(int(achat.id)))

    return AchatPaymentRead.model_validate(achat)


class QboPullResult(BaseModel):
    imported: int
    unmatched_project: int
    imported_paid: int
    skipped_existing: int
    paid_synced: int = 0
    total_qbo_bills: int


@router.post(
    "/sync-from-qbo",
    response_model=QboPullResult,
    summary="Importe les Bills QuickBooks absents de Kratos",
)
async def sync_from_qbo(
    db: DBSession,
    _: RequireManager,
    since_days: int = 180,
) -> QboPullResult:
    """Pull les Bills QB recents qui n'ont pas encore d'Achat
    Kratos correspondant. Garde anti-doublon via qbo_bill_id.

    - Cree un Fournisseur Kratos si le vendor QB est inconnu.
    - Tente de matcher le projet via la Class QB (= adresse).
    - Marque l'Achat paye s'il existe une BillPayment QB liee.
    - is_billable forcement False (refacturation reste pilotee
      depuis Kratos).
    """
    try:
        stats = await pull_new_bills_from_qbo(db, since_days=since_days)
    except QboPullError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        )
    return QboPullResult(**stats)


# ── Déduplication des achats ────────────────────────────────────────
# Cas typique : un achat saisi dans Kratos est poussé vers QB (Bill /
# Purchase) puis RÉ-IMPORTÉ par le pull → un 2e achat « QB » identique.
# Dans le calcul de coût projet, les DEUX sont comptés → coût gonflé.
class DedupeGroup(BaseModel):
    key: str
    reference: Optional[str] = None
    fournisseur_id: Optional[int] = None
    kept_id: int
    removed_ids: list[int]


class DedupeResult(BaseModel):
    dry_run: bool
    groups_found: int
    duplicates_removed: int
    details: list[DedupeGroup]


def _keeper_score(a: Achat) -> tuple:
    """Plus le score est haut, plus l'achat est « riche » → à conserver.
    On garde celui qui est facturé / a une pièce jointe / un paiement QB,
    et à défaut le plus ancien (id le plus petit)."""
    return (
        1 if a.facture_item_id is not None else 0,
        1 if a.invoiced_at is not None else 0,
        1 if a.has_receipt_image else 0,
        1 if a.qbo_bill_payment_id else 0,
        -a.id,  # tie-break : garder le plus ancien (id min)
    )


@router.post(
    "/dedupe",
    response_model=DedupeResult,
    summary="Détecte (et supprime si confirm) les achats en double",
)
async def dedupe_achats(
    db: DBSession,
    _: RequireManager,
    confirm: bool = False,
) -> DedupeResult:
    """Détecte les achats en double et, si ``confirm=true``, supprime les
    redondants en gardant le plus complet (facturé / pièce jointe / le
    plus ancien). PAR DÉFAUT (``confirm=false``) : APERÇU seul, rien n'est
    supprimé.

    Deux clés de regroupement, toutes deux sûres :
      1. Même transaction QuickBooks — un Id présent dans ``qbo_bill_id``
         OU ``qbo_purchase_id`` de plusieurs achats (cas saisie→QB→ré-import,
         où l'Id de la Purchase poussée est stocké dans qbo_bill_id).
      2. Même (fournisseur, n° de facture fournisseur) — un n° de facture
         identifie un seul document fournisseur.
    """
    from collections import defaultdict

    achats = list((await db.execute(select(Achat))).scalars().all())

    grouped_ids: set[int] = set()
    groups: list[tuple[str, list[Achat]]] = []

    # 1) Même transaction QB (cross-champ qbo_bill_id / qbo_purchase_id).
    by_qb: dict[str, dict[int, Achat]] = defaultdict(dict)
    for a in achats:
        for qid in (a.qbo_bill_id, a.qbo_purchase_id):
            if qid:
                by_qb[str(qid)][a.id] = a
    for qid, members in by_qb.items():
        if len(members) > 1:
            groups.append((f"qb:{qid}", list(members.values())))
            grouped_ids.update(members.keys())

    # 2) Même (fournisseur, n° facture fournisseur) — pour les doublons
    #    pas reliés par un Id QB. n° de facture vide → ignoré.
    by_inv: dict[tuple, dict[int, Achat]] = defaultdict(dict)
    for a in achats:
        if a.id in grouped_ids:
            continue
        inv = (a.supplier_invoice_number or "").strip().lower()
        if inv and a.fournisseur_id:
            by_inv[(a.fournisseur_id, inv)][a.id] = a
    for (fid, inv), members in by_inv.items():
        if len(members) > 1:
            groups.append((f"inv:{fid}:{inv}", list(members.values())))
            grouped_ids.update(members.keys())

    details: list[DedupeGroup] = []
    removed = 0
    for key, members in groups:
        keeper = max(members, key=_keeper_score)
        to_remove = [a for a in members if a.id != keeper.id]
        if not to_remove:
            continue
        details.append(
            DedupeGroup(
                key=key,
                reference=(
                    keeper.supplier_invoice_number or keeper.reference
                ),
                fournisseur_id=keeper.fournisseur_id,
                kept_id=keeper.id,
                removed_ids=[a.id for a in to_remove],
            )
        )
        removed += len(to_remove)
        if confirm:
            for a in to_remove:
                await db.delete(a)
    if confirm and removed:
        await db.flush()

    return DedupeResult(
        dry_run=not confirm,
        groups_found=len(details),
        duplicates_removed=removed,
        details=details,
    )
