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
    await push_facture_now(facture_id)


async def push_facture_payments_now(facture_id: int) -> None:
    """Push DÉLIBÉRÉ des PAIEMENTS d'une facture vers QB (enregistrement
    d'un paiement). Ne re-pousse pas le corps de la facture → fiable même
    sur une facture migrée. Non conditionné à l'interrupteur de migration.
    """
    try:
        from app.services.facture_qbo import push_facture_payments_only

        async with AsyncSessionLocal() as db:
            await push_facture_payments_only(db, facture_id)
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("push_facture_payments_now %s: %s", facture_id, exc)


async def push_facture_now(facture_id: int) -> None:
    """Push DÉLIBÉRÉ d'une facture vers QB — PAS conditionné à
    l'interrupteur de migration `qbo_auto_sync`.

    Sert aux actions explicites de l'utilisateur sur UNE facture précise :
    enregistrement d'un paiement, rattachement à un projet. Ce ne sont pas
    des créations de masse (migration), donc on les reflète TOUJOURS dans
    QuickBooks. Idempotent : `qbo_invoice_id` / `qbo_payment_id` évitent
    tout doublon (création la 1ʳᵉ fois, mise à jour ensuite).
    """
    try:
        from app.services.facture_qbo import sync_facture_to_qbo

        async with AsyncSessionLocal() as db:
            await sync_facture_to_qbo(db, facture_id)
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.error("push_facture_now %s: %s", facture_id, exc)
        # Rend l'échec VISIBLE sur la fiche facture (session fraîche).
        from app.services.facture_qbo import record_facture_sync_error

        await record_facture_sync_error(facture_id, str(exc))


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


async def push_client_update_qbo_now(
    client_id: int, old_name: str | None = None
) -> None:
    """Reflète la fiche client Kratos dans QuickBooks après une
    MODIFICATION (nom affiché, courriel, téléphone, adresse). Action
    délibérée de l'utilisateur → PAS conditionné à l'interrupteur
    `qbo_auto_sync`.

    Résolution du client QB, dans l'ordre : lien existant
    (`qbo_customer_id`), sinon adoption par COURRIEL (clé d'identité —
    couvre la fiche renommée, ex. « Zalec Bruneau » → « Zimmo
    immobilier »), sinon par nom exact, sinon par l'ANCIEN nom
    (`old_name` — correction d'une faute de frappe sur une fiche sans
    courriel ni lien). Introuvable → on ne crée rien ici (la création
    reste au flux bon/facture). Best-effort."""
    try:
        import asyncio

        from app.integrations.quickbooks import get_qbo
        from app.models.client import Client

        qbo = get_qbo()
        await qbo._load_refresh_from_db()
        if not qbo.ready:
            return
        # La tâche part pendant la requête PUT : on laisse sa
        # transaction se commiter avant de lire la fiche.
        await asyncio.sleep(2)
        async with AsyncSessionLocal() as db:
            client = (
                await db.execute(select(Client).where(Client.id == client_id))
            ).scalar_one_or_none()
            if client is None:
                return
            cust = None
            if client.qbo_customer_id:
                cust = await qbo.get_customer(client.qbo_customer_id)
            if cust is None and client.email:
                cust = await qbo.find_customer_by_email(client.email)
            if cust is None and client.name:
                cust = await qbo.find_customer_by_name(client.name)
            _old = (old_name or "").strip()
            if (
                cust is None
                and _old
                and _old.lower() != (client.name or "").strip().lower()
            ):
                cust = await qbo.find_customer_by_name(_old)
            if cust is None:
                return
            cid = str(cust.get("Id") or "")
            if not cid:
                return
            if client.qbo_customer_id != cid:
                client.qbo_customer_id = cid
                await db.commit()
            # Mise à jour sparse seulement si quelque chose diffère.
            qb_name = (cust.get("DisplayName") or "").strip()
            qb_email = (
                (cust.get("PrimaryEmailAddr") or {}).get("Address") or ""
            ).strip()
            qb_phone = (
                (cust.get("PrimaryPhone") or {}).get("FreeFormNumber") or ""
            ).strip()
            qb_addr = ((cust.get("BillAddr") or {}).get("Line1") or "").strip()
            k_name = (client.name or "").strip()
            k_email = (client.email or "").strip()
            k_phone = (client.phone or "").strip()
            k_addr = (client.address or "").strip()
            if (
                (k_name and k_name != qb_name)
                or (k_email and k_email.lower() != qb_email.lower())
                or (k_phone and k_phone != qb_phone)
                or (k_addr and k_addr != qb_addr)
            ):
                await qbo.update_customer(
                    cid,
                    display_name=k_name or None,
                    email=k_email or None,
                    phone=k_phone or None,
                    billing_address=k_addr or None,
                )
                log.info(
                    "Client %s reflété dans QB (customer %s « %s »)",
                    client_id, cid, k_name,
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("push_client_update_qbo_now %s: %s", client_id, exc)
