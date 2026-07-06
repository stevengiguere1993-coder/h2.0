"""Webhook QuickBooks Online → Kratos (reverse-sync).

Intuit POST ``/api/v1/qbo/webhook`` à chaque changement d'une entité
abonnée (Purchase, Bill…). On vérifie la signature (``intuit-signature`` =
base64 du HMAC-SHA256 du CORPS BRUT avec le « verifier token »), puis, pour
chaque dépense liée à un achat Kratos, on met à jour le MODE DE PAIEMENT et
la DATE d'après l'état QBO — utile quand la dépense a été rapprochée /
ajustée dans QuickBooks (date bancaire, carte réellement utilisée).

On ne RE-POUSSE jamais vers QBO depuis ici → pas de boucle. On ne traite
jamais un corps dont la signature n'est pas vérifiée.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
from datetime import date
from typing import List, Optional, Tuple

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.integrations.quickbooks import get_qbo
from app.models.achat import Achat
from app.models.qbo_account_map import QboAccountMap

log = logging.getLogger("qbo.webhook")
router = APIRouter(prefix="/qbo", tags=["qbo-webhook"])

# Mode de paiement Kratos ↔ colonne de nom de compte dans qbo_account_maps.
_METHOD_ACCOUNT_FIELDS = {
    "cheque_horizon": "cheque_horizon_account",
    "cc_steven": "cc_steven_account",
    "cc_michael": "cc_michael_account",
    "cc_olivier": "cc_olivier_account",
    "cc_christian": "cc_christian_account",
}


def _verify_signature(raw_body: bytes, signature_header: str) -> bool:
    """Vérifie la signature d'un webhook QBO. Intuit envoie
    ``intuit-signature`` = base64(HMAC-SHA256(corps_brut, verifier_token)).
    Sans jeton configuré ou sans en-tête, on refuse (fail-closed)."""
    token = settings.qbo_webhook_verifier_token
    if not token or not signature_header:
        return False
    computed = base64.b64encode(
        hmac.new(token.encode(), raw_body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(computed, signature_header)


def _norm_account_name(name: Optional[str]) -> str:
    """Normalise un nom de compte pour comparaison : minuscules, sans le
    suffixe de type « (Credit Card) » éventuel, espaces compactés."""
    if not name:
        return ""
    cleaned = re.sub(r"\s*\((?:[^()]*)\)\s*$", "", name).strip()
    return re.sub(r"\s+", " ", cleaned).lower()


def _reverse_payment_method(
    account_map: Optional[QboAccountMap], account_name: Optional[str]
) -> Optional[str]:
    """Nom du compte de paiement QBO → mode de paiement Kratos (inverse du
    mapping qbo_account_maps). None si aucune correspondance."""
    if account_map is None:
        return None
    target = _norm_account_name(account_name)
    if not target:
        return None
    for method, field in _METHOD_ACCOUNT_FIELDS.items():
        if _norm_account_name(getattr(account_map, field, None)) == target:
            return method
    return None


def _parse_txn_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def qbo_webhook(request: Request) -> Response:
    raw = await request.body()
    signature = request.headers.get("intuit-signature", "")
    if not _verify_signature(raw, signature):
        # 401 : Intuit réessaiera. On ne traite jamais un corps non vérifié.
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        payload = json.loads(raw or b"{}")
    except (ValueError, TypeError):
        return Response(status_code=status.HTTP_200_OK)

    # Collecte des (entity_name, entity_id) de type dépense qui ont changé,
    # en ignorant les autres compagnies et les suppressions.
    realm = str(settings.qbo_realm_id or "")
    changed: List[Tuple[str, str]] = []
    pull_needed = False
    for note in payload.get("eventNotifications") or []:
        if realm and str(note.get("realmId") or "") != realm:
            continue
        entities = (note.get("dataChangeEvent") or {}).get("entities") or []
        for ent in entities:
            name = str(ent.get("name") or "")
            eid = str(ent.get("id") or "")
            op = str(ent.get("operation") or "")
            if op in ("Delete", "Merge"):
                continue
            # Tout événement « coût » déclenche un import complet LIVE
            # (nouveaux coûts, fournisseurs, paiements, reçus) — pas
            # seulement les Purchase/Bill liés.
            if name in (
                "Purchase",
                "Bill",
                "BillPayment",
                "Attachable",
                "Vendor",
            ):
                pull_needed = True
            if not eid or name not in ("Purchase", "Bill"):
                continue
            changed.append((name, eid))

    if not changed and not pull_needed:
        return Response(status_code=status.HTTP_200_OK)

    qbo = get_qbo()
    async with AsyncSessionLocal() as db:
        account_map = (
            await db.execute(
                select(QboAccountMap).where(QboAccountMap.id == 1)
            )
        ).scalar_one_or_none()
        for name, eid in changed:
            try:
                await _apply_reverse_sync(db, qbo, account_map, name, eid)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "reverse-sync QBO %s %s échoué: %s", name, eid, exc
                )
        await db.commit()

    # Import complet QB → Kratos en ARRIÈRE-PLAN (même logique que le pull
    # horaire : nouveaux coûts, création des fournisseurs, paiements,
    # reçus, dédup). Débounce 30 s : une rafale d'événements Intuit ne
    # lance qu'un seul pull. Le webhook répond 200 tout de suite (Intuit
    # exige une réponse rapide, sinon il ré-émet).
    if pull_needed:
        asyncio.create_task(_run_cost_pull_debounced())

    # Toujours 200 : sinon Intuit ré-émet en boucle (le traitement est
    # best-effort, chaque entité est isolée).
    return Response(status_code=status.HTTP_200_OK)


# Débounce du pull complet déclenché par webhook : une rafale de
# notifications Intuit (plusieurs entités modifiées d'un coup) ne doit
# lancer qu'UN import, et jamais deux en parallèle.
_pull_lock = asyncio.Lock()
_last_pull_monotonic: float = 0.0
_PULL_DEBOUNCE_SECONDS = 30.0


async def _run_cost_pull_debounced() -> None:
    global _last_pull_monotonic
    import time

    if _pull_lock.locked():
        return  # un pull est déjà en cours — il couvrira ces événements
    async with _pull_lock:
        if time.monotonic() - _last_pull_monotonic < _PULL_DEBOUNCE_SECONDS:
            return
        _last_pull_monotonic = time.monotonic()
        try:
            from app.services.qbo_cost_pull import (
                pull_project_costs_from_qbo,
            )

            async with AsyncSessionLocal() as db:
                res = await pull_project_costs_from_qbo(db, dry_run=False)
                await db.commit()
            log.info("Pull QB→Kratos déclenché par webhook : %s", res)
        except Exception:  # noqa: BLE001
            log.warning(
                "Pull QB→Kratos (webhook) échoué", exc_info=True
            )


async def _apply_reverse_sync(
    db, qbo, account_map: Optional[QboAccountMap], name: str, eid: str
) -> None:
    """Met à jour l'achat Kratos lié à la dépense QBO ``eid`` (mode de
    paiement + date) d'après l'état actuel de QBO. No-op si aucun achat
    n'est lié à cette transaction."""
    achat = (
        await db.execute(
            select(Achat).where(Achat.qbo_bill_id == str(eid))
        )
    ).scalar_one_or_none()
    if achat is None:
        return  # pas une dépense qu'on suit

    obj = (
        await qbo.get_purchase(eid)
        if name == "Purchase"
        else await qbo.get_bill(eid)
    )
    if not obj:
        return

    changed_fields: List[str] = []

    # Date : TxnDate QBO → invoice_date Kratos.
    txn_date = _parse_txn_date(obj.get("TxnDate"))
    if txn_date and txn_date != achat.invoice_date:
        achat.invoice_date = txn_date
        changed_fields.append("date")

    # Mode de paiement : compte de paiement QBO (Purchase) → payment_method.
    if name == "Purchase":
        acct_ref = obj.get("AccountRef") or {}
        acct_name = acct_ref.get("name")
        if not acct_name and acct_ref.get("value"):
            acct = await qbo.get_account(str(acct_ref["value"]))
            acct_name = (acct or {}).get("Name")
        method = _reverse_payment_method(account_map, acct_name)
        if method and method != (achat.payment_method or ""):
            achat.payment_method = method
            changed_fields.append("mode de paiement")

    # Rafraîchit le SyncToken pour éviter un « stale token » au prochain push.
    tok = obj.get("SyncToken")
    if tok is not None:
        achat.qbo_sync_token = str(tok)

    if changed_fields:
        log.info(
            "Reverse-sync QBO → achat %s : %s mis à jour depuis %s %s",
            achat.id,
            ", ".join(changed_fields),
            name,
            eid,
        )
