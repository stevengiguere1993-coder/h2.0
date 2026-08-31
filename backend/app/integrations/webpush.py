"""WebPush — envoi de notifications navigateur (PWA installée).

Utilise pywebpush + VAPID keys (configurées via env). Best-effort :
si une subscription échoue (410 Gone, 404 Unsubscribed, network), on
log et on retire la subscription de la base pour ne pas la retenter.

Usage typique ::

    from app.integrations.webpush import push_to_user

    await push_to_user(
        db,
        user_id=42,
        title="🚨 Urgence locataire",
        body="Marie Tremblay vient d'appeler — fuite d'eau au 4567 rue X",
        href="/telephonie?call=123",
        tag="urgence",
    )

Si `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` ne
sont pas configurés, `push_to_user` est un no-op silencieux.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Iterable, Optional

from sqlalchemy import select

from app.models.push_subscription import PushSubscription

log = logging.getLogger(__name__)


def _vapid_configured() -> bool:
    return bool(
        os.getenv("VAPID_PUBLIC_KEY")
        and os.getenv("VAPID_PRIVATE_KEY")
    )


async def push_to_user(
    db,
    *,
    user_id: int,
    title: str,
    body: Optional[str] = None,
    href: Optional[str] = None,
    tag: Optional[str] = None,
    icon: Optional[str] = None,
    errors_out: Optional[list] = None,
) -> int:
    """Pousse une notif à toutes les subscriptions du user. Renvoie
    le nombre de notifs effectivement envoyées.

    ``errors_out`` : liste où consigner les échecs par subscription
    (chaînes courtes) — le /push/test s'en sert pour que l'échec soit
    VISIBLE dans l'UI au lieu de mourir dans les logs (retour Phil
    2026-08-31 : abonné, test jamais reçu, aucun indice)."""
    if not _vapid_configured():
        if errors_out is not None:
            errors_out.append("VAPID non configuré sur le serveur.")
        return 0
    subs = (
        await db.execute(
            select(PushSubscription).where(
                PushSubscription.user_id == user_id
            )
        )
    ).scalars().all()
    if not subs:
        if errors_out is not None:
            errors_out.append("Aucun abonnement enregistré pour ce compte.")
        return 0
    return await _push_to_subscriptions(
        db, subs, title=title, body=body, href=href, tag=tag, icon=icon,
        errors_out=errors_out,
    )


async def push_to_users(
    db,
    *,
    user_ids: Iterable[int],
    title: str,
    body: Optional[str] = None,
    href: Optional[str] = None,
    tag: Optional[str] = None,
    icon: Optional[str] = None,
) -> int:
    """Broadcast à plusieurs users en un seul query."""
    if not _vapid_configured():
        return 0
    uids = list({int(u) for u in user_ids if u})
    if not uids:
        return 0
    subs = (
        await db.execute(
            select(PushSubscription).where(
                PushSubscription.user_id.in_(uids)
            )
        )
    ).scalars().all()
    if not subs:
        return 0
    return await _push_to_subscriptions(
        db, subs, title=title, body=body, href=href, tag=tag, icon=icon
    )


async def _push_to_subscriptions(
    db,
    subs,
    *,
    title: str,
    body: Optional[str],
    href: Optional[str],
    tag: Optional[str],
    icon: Optional[str],
    errors_out: Optional[list] = None,
) -> int:
    from datetime import datetime, timezone

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        log.warning("pywebpush not installed — WebPush disabled")
        if errors_out is not None:
            errors_out.append("pywebpush absent du serveur.")
        return 0

    payload = json.dumps(
        {
            "title": title,
            "body": body or "",
            "href": href or "/",
            "tag": tag or "horizon",
            "icon": icon or "/pwa/icon-192.png",
        }
    )
    vapid_claims = {"sub": os.getenv("VAPID_SUBJECT", "mailto:info@horizonservicesimmobiliers.com")}
    private_key = os.getenv("VAPID_PRIVATE_KEY", "")
    sent = 0
    to_delete: list[int] = []
    for s in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": s.endpoint,
                    "keys": {"p256dh": s.p256dh, "auth": s.auth},
                },
                data=payload,
                vapid_private_key=private_key,
                vapid_claims=vapid_claims,
            )
            sent += 1
            s.last_used_at = datetime.now(timezone.utc)
        except WebPushException as exc:  # type: ignore[misc]
            code = getattr(exc.response, "status_code", None) if hasattr(exc, "response") else None
            # 404/410 = subscription expirée ou révoquée → on purge.
            if code in (404, 410):
                to_delete.append(s.id)
                if errors_out is not None:
                    errors_out.append(
                        "Abonnement expiré (purgé) — réactive les "
                        "notifications sur l'appareil."
                    )
            else:
                log.warning(
                    "WebPush failed for sub %s: %s (code=%s)",
                    s.id,
                    exc,
                    code,
                )
                if errors_out is not None:
                    body_txt = ""
                    if getattr(exc, "response", None) is not None:
                        try:
                            body_txt = (exc.response.text or "")[:200]
                        except Exception:  # noqa: BLE001
                            body_txt = ""
                    errors_out.append(
                        f"Refus du service push (code={code}) : "
                        f"{body_txt or exc}"[:300]
                    )
        except Exception as exc:  # noqa: BLE001
            log.warning("WebPush unexpected error for sub %s: %s", s.id, exc)
            if errors_out is not None:
                errors_out.append(
                    f"Erreur d'envoi ({type(exc).__name__}) : {exc}"[:300]
                )
    if to_delete:
        from sqlalchemy import delete as sa_delete

        await db.execute(
            sa_delete(PushSubscription).where(
                PushSubscription.id.in_(to_delete)
            )
        )
        log.info("WebPush purged %d expired subscriptions", len(to_delete))
    await db.flush()
    return sent
