"""Déduire le MODE DE PAIEMENT réel d'un Bill QuickBooks payé.

Quand on importe une facture fournisseur (Bill) déjà payée depuis QB, on ne
doit pas la laisser en « Sur compte » (bill_to_pay) : une fois payée, elle
est classée selon le paiement réellement fait (chèque / carte de telle
personne). On lit la BillPayment liée et on remonte le COMPTE utilisé
(BankAccountRef pour un chèque, CCAccountRef pour une carte) puis on le
rapproche du mapping `qbo_account_maps` pour retrouver le mode Horizon exact
(cheque_horizon / cc_steven / cc_michael / cc_olivier / cc_christian).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.qbo_account_map import QboAccountMap

log = logging.getLogger(__name__)


async def _account_id_to_method(qbo: Any, db: AsyncSession) -> dict[str, str]:
    """Compte QB (Id) → mode de paiement Horizon, via le nom du compte
    configuré dans qbo_account_maps."""
    row = (
        await db.execute(select(QboAccountMap).where(QboAccountMap.id == 1))
    ).scalar_one_or_none()
    if row is None:
        return {}
    name_to_method: dict[str, str] = {}
    for attr, method in (
        ("cheque_horizon_account", "cheque_horizon"),
        ("cc_steven_account", "cc_steven"),
        ("cc_michael_account", "cc_michael"),
        ("cc_olivier_account", "cc_olivier"),
        ("cc_christian_account", "cc_christian"),
    ):
        nm = (getattr(row, attr, None) or "").strip().lower()
        if nm:
            name_to_method[nm] = method
    if not name_to_method:
        return {}
    try:
        accounts = await qbo.query("SELECT Id, Name FROM Account MAXRESULTS 1000")
    except Exception as exc:  # noqa: BLE001
        log.warning("classify: query Account échouée: %s", exc)
        return {}
    out: dict[str, str] = {}
    for a in accounts:
        nm = (a.get("Name") or "").strip().lower()
        if nm in name_to_method and a.get("Id"):
            out[str(a["Id"])] = name_to_method[nm]
    return out


async def build_paid_bill_method_index(
    qbo: Any, db: AsyncSession
) -> dict[str, str]:
    """Index bill_id (QB) → mode de paiement Horizon réel.

    UNE seule query BillPayment (+ une query Account). Pour chaque paiement,
    on retrouve le compte utilisé et on le mappe ; à défaut, un chèque tombe
    sur `cheque_horizon` (compte chèque unique). Une carte non reconnue n'est
    pas devinée (on laisse l'appelant garder « à payer »)."""
    id_to_method = await _account_id_to_method(qbo, db)
    try:
        rows = await qbo.query("SELECT * FROM BillPayment MAXRESULTS 1000")
    except Exception as exc:  # noqa: BLE001
        log.warning("classify: query BillPayment échouée: %s", exc)
        return {}
    out: dict[str, str] = {}
    for p in rows:
        pay_type = (p.get("PayType") or "").lower()
        acc_id: Optional[str] = None
        if pay_type == "check":
            acc_id = (
                (p.get("CheckPayment") or {}).get("BankAccountRef") or {}
            ).get("value")
        elif pay_type == "creditcard":
            acc_id = (
                (p.get("CreditCardPayment") or {}).get("CCAccountRef") or {}
            ).get("value")
        method = id_to_method.get(str(acc_id)) if acc_id else None
        if not method and pay_type == "check":
            # Repli sûr : un chèque ne peut venir que du compte chèque Horizon.
            method = "cheque_horizon"
        if not method:
            continue
        for line in p.get("Line") or []:
            for ltxn in line.get("LinkedTxn") or []:
                if ltxn.get("TxnType") == "Bill" and ltxn.get("TxnId"):
                    out.setdefault(str(ltxn["TxnId"]), method)
    return out
