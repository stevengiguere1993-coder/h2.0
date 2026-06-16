"""Synchro QBO automatique (préparée, désactivée par défaut).

Interrupteur global `qbo_auto_sync` (AutomationSetting). **Fail-closed** :
tant qu'il n'est pas explicitement activé, RIEN ne part automatiquement —
on s'en sert seulement APRÈS avoir validé la migration de masse, pour ne
pas créer de doublons pendant que les ID QBO ne sont pas tous reliés.

Idempotent : on ne pousse pas un enregistrement qui a déjà son ID QBO.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.automation_setting import AutomationSetting

log = logging.getLogger(__name__)

QBO_AUTO_SYNC_KEY = "qbo_auto_sync"


async def is_qbo_auto_sync_enabled() -> bool:
    """Fail-closed : désactivé tant qu'aucune ligne `enabled=True`."""
    try:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(AutomationSetting).where(
                        AutomationSetting.key == QBO_AUTO_SYNC_KEY
                    )
                )
            ).scalar_one_or_none()
            return bool(row and row.enabled)
    except Exception:  # noqa: BLE001
        return False


async def autopush_facture(facture_id: int) -> None:
    if not await is_qbo_auto_sync_enabled():
        return
    try:
        from app.services.facture_qbo import sync_facture_to_qbo

        async with AsyncSessionLocal() as db:
            await sync_facture_to_qbo(db, facture_id)
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("autopush facture %s: %s", facture_id, exc)


async def autopush_soumission(soumission_id: int) -> None:
    if not await is_qbo_auto_sync_enabled():
        return
    try:
        from app.services.soumission_qbo import sync_soumission_to_qbo

        async with AsyncSessionLocal() as db:
            await sync_soumission_to_qbo(db, soumission_id)
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("autopush soumission %s: %s", soumission_id, exc)


async def autopush_client(client_id: int) -> None:
    if not await is_qbo_auto_sync_enabled():
        return
    try:
        from app.integrations.quickbooks import get_qbo
        from app.models.client import Client

        async with AsyncSessionLocal() as db:
            client = (
                await db.execute(select(Client).where(Client.id == client_id))
            ).scalar_one_or_none()
            if client is None or client.qbo_customer_id:
                return  # absent ou déjà relié → idempotent
            qbo = get_qbo()
            await qbo._load_refresh_from_db()
            if not qbo.ready:
                return
            cust = await qbo.ensure_customer(
                display_name=client.name,
                email=client.email,
                phone=client.phone,
                billing_address=client.address,
            )
            cid = str(cust.get("Id") or "")
            if cid:
                client.qbo_customer_id = cid
                await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("autopush client %s: %s", client_id, exc)
