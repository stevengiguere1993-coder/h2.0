"""Logique de paiement des Achats fournisseurs.

Regles metier :
- Un achat paye par cheque Horizon / carte de credit est paye au
  moment de l'achat (status = paid, paid_at = received_at). Il ne
  doit pas trainer dans l'onglet "A payer".
- Un achat paye par facture fournisseur (bill_to_pay) reste en
  status "received" jusqu'a paiement manuel. Sa date d'echeance
  est calculee a la creation : received_at + payment_terms_days
  du fournisseur (30 par defaut).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.achat import Achat, AchatStatus, PaymentMethod
from app.models.fournisseur import Fournisseur


DEFAULT_PAYMENT_TERMS_DAYS = 30


async def _fournisseur_terms(
    db: AsyncSession, fournisseur_id: Optional[int]
) -> int:
    """Retourne le delai net du fournisseur, ou 30 par defaut."""
    if not fournisseur_id:
        return DEFAULT_PAYMENT_TERMS_DAYS
    f = (
        await db.execute(
            select(Fournisseur).where(Fournisseur.id == fournisseur_id)
        )
    ).scalar_one_or_none()
    if f is None or f.payment_terms_days is None:
        return DEFAULT_PAYMENT_TERMS_DAYS
    return int(f.payment_terms_days)


async def apply_payment_defaults(db: AsyncSession, achat: Achat) -> None:
    """Applique a la creation :
    - Si payment_method != bill_to_pay → status=paid, paid_at calee
      sur received_at (ou now si manquant). Cas: cheque, CC.
    - Si payment_method == bill_to_pay → due_at = received_at +
      payment_terms_days du fournisseur (defaut 30).

    Idempotent : si status est deja explicite a paid ou cancelled,
    on respecte. Si due_at est deja saisi, on respecte aussi.
    """
    pm = (achat.payment_method or "").strip() or None
    now = datetime.now(timezone.utc)
    if achat.received_at is None:
        achat.received_at = now

    if pm and pm != PaymentMethod.BILL_TO_PAY.value:
        # Paye au moment de l'achat (cheque, CC).
        if achat.status == AchatStatus.RECEIVED.value:
            achat.status = AchatStatus.PAID.value
        if achat.paid_at is None:
            achat.paid_at = achat.received_at
        # Pas d'echeance pour les paiements immediats.
        achat.due_at = None
        return

    if pm == PaymentMethod.BILL_TO_PAY.value and achat.due_at is None:
        terms = await _fournisseur_terms(db, achat.fournisseur_id)
        achat.due_at = achat.received_at + timedelta(days=terms)


async def mark_achat_paid(
    db: AsyncSession,
    achat: Achat,
    *,
    payment_method: str,
    paid_at: Optional[datetime] = None,
) -> None:
    """Marque un achat paye. Remplace payment_method (utile quand un
    achat etait bill_to_pay et qu'on le paye finalement par cheque
    ou CC). Met paid_at a la date fournie ou now."""
    achat.payment_method = payment_method
    achat.paid_at = paid_at or datetime.now(timezone.utc)
    achat.status = AchatStatus.PAID.value
    # L'echeance n'a plus de sens une fois paye.
    achat.due_at = None
