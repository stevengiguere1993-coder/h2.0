"""eSign — job quotidien (méga-cron /cron-runner/run/all-daily).

Deux responsabilités :

1. **Expiration** : les documents `envoye` dont `expires_at` est
   dépassée passent en statut `expire` (les liens publics renvoient
   410 dès la date passée, ce job ne fait qu'aligner le statut et
   journaliser l'événement).

2. **Rappels automatiques** : pour les documents `envoye` avec
   `reminder_days` configuré, chaque signataire en attente (et dont
   c'est le tour, en mode séquentiel) reçoit une relance courriel si
   aucune action depuis `reminder_days` jours — maximum
   ``_MAX_AUTO_REMINDERS`` relances automatiques par signataire.

Best-effort signataire par signataire : un envoi qui échoue ne bloque
pas les autres.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

log = logging.getLogger(__name__)

_MAX_AUTO_REMINDERS = 3


async def run() -> dict:
    from app.db.session import AsyncSessionLocal
    from app.models.entreprise import Entreprise
    from app.models.esign import (
        EsignDocument,
        EsignDocumentStatus,
        EsignEvent,
        EsignSigner,
    )
    from app.services.esign_send import (
        send_signer_invitation,
        signers_to_invite,
    )

    now = datetime.now(timezone.utc)
    expired = 0
    reminders = 0
    errors = 0

    async with AsyncSessionLocal() as db:
        # ── 1. Expiration ────────────────────────────────────────────
        stale = list(
            (
                await db.execute(
                    select(EsignDocument).where(
                        EsignDocument.status
                        == EsignDocumentStatus.ENVOYE.value,
                        EsignDocument.expires_at.isnot(None),
                        EsignDocument.expires_at <= now,
                    )
                )
            ).scalars()
        )
        for doc in stale:
            doc.status = EsignDocumentStatus.EXPIRE.value
            db.add(
                EsignEvent(
                    document_id=doc.id,
                    type="expire",
                    detail="date limite dépassée (cron quotidien)",
                )
            )
            expired += 1
        if stale:
            await db.commit()

        # ── 2. Rappels automatiques ──────────────────────────────────
        docs = list(
            (
                await db.execute(
                    select(EsignDocument).where(
                        EsignDocument.status
                        == EsignDocumentStatus.ENVOYE.value,
                        EsignDocument.reminder_days.isnot(None),
                    )
                )
            ).scalars()
        )
        for doc in docs:
            signers = list(
                (
                    await db.execute(
                        select(EsignSigner)
                        .where(EsignSigner.document_id == doc.id)
                        .order_by(
                            EsignSigner.order_index, EsignSigner.id
                        )
                    )
                ).scalars()
            )
            ent_name = None
            if doc.entreprise_id:
                ent_name = (
                    await db.execute(
                        select(Entreprise.name).where(
                            Entreprise.id == doc.entreprise_id
                        )
                    )
                ).scalar_one_or_none()
            threshold = (doc.reminder_days or 0) * 86400
            if threshold <= 0:
                continue
            for s in signers_to_invite(doc, signers):
                if s.sent_at is None:
                    continue  # pas encore invité (séquentiel) — rien à relancer
                if (s.auto_reminder_count or 0) >= _MAX_AUTO_REMINDERS:
                    continue
                base = s.last_reminder_at or s.sent_at
                if base.tzinfo is None:
                    base = base.replace(tzinfo=timezone.utc)
                if (now - base).total_seconds() < threshold:
                    continue
                try:
                    await send_signer_invitation(
                        db, doc, s, ent_name, reminder=True
                    )
                    s.auto_reminder_count = (s.auto_reminder_count or 0) + 1
                    s.last_reminder_at = now
                    db.add(
                        EsignEvent(
                            document_id=doc.id,
                            signer_id=s.id,
                            type="relance",
                            detail=(
                                f"automatique #{s.auto_reminder_count} "
                                f"({s.email})"
                            ),
                        )
                    )
                    reminders += 1
                    await db.commit()
                except Exception:  # noqa: BLE001
                    errors += 1
                    log.exception(
                        "eSign cron : relance auto échouée "
                        "(doc %s, signataire %s)",
                        doc.id, s.id,
                    )
                    await db.rollback()

    result = {"expired": expired, "reminders": reminders, "errors": errors}
    log.info("eSign cron : %s", result)
    return result
