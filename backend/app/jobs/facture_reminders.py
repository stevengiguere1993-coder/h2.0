"""Daily cron: mark overdue invoices and send escalating reminders.

Runs once a day. For every Facture in status "sent" / "overdue":
- If due_at is in the past and status is still "sent", bump to "overdue".
- Send a reminder email every 4 days while the invoice stays overdue
  and unpaid — no cap, it keeps going until a payment is recorded and
  the status flips to "paid". The tone escalates with reminder_count:
  friendly -> firm -> final.
- next_reminder_at can be set manually on the invoice to override when
  the next reminder fires (push it back or bring it forward).

The reminder body mentions the invoice reference, total and days
overdue. Staff is cc'd on every send so they see the pressure trail.

Usage (Render cron):
    python -m app.jobs.facture_reminders
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.integrations.email_graph import get_mailer
from app.models.client import Client
from app.models.facture import Facture, FactureStatus
from app.models.facture_item import FactureItem
from app.models.payment import Payment
from app.services.facture_pdf import render_facture_pdf
from app.integrations.email_graph import EmailAttachment

log = logging.getLogger(__name__)


# Cadence des rappels : un rappel tous les 4 jours tant que la facture
# est en retard et impayée — aucun plafond, ça continue jusqu'à
# l'enregistrement du paiement (passage au statut "paid").
REMINDER_INTERVAL_DAYS = 4

# Le ton monte avec le nombre de rappels déjà envoyés : 1er = amical,
# 2e = ferme, 3e et suivants = avis final.
_SUBJECT_PREFIX = {
    "friendly": "Rappel",
    "firm": "Rappel important",
    "final": "Avis final",
}


def _body_html(tone: str, ref: str, total: float, days_late: int) -> str:
    total_str = f"{total:,.2f} $ CAD".replace(",", " ")
    if tone == "friendly":
        lead = (
            f"Petit rappel amical : la facture <strong>{ref}</strong> "
            f"({total_str}) est échue depuis {days_late} jour"
            f"{'s' if days_late > 1 else ''}."
        )
    elif tone == "firm":
        lead = (
            f"La facture <strong>{ref}</strong> ({total_str}) est "
            f"maintenant en retard de {days_late} jours. Merci de "
            f"procéder au paiement dans les plus brefs délais."
        )
    else:  # final
        lead = (
            f"Avis final : la facture <strong>{ref}</strong> ({total_str}) "
            f"est en retard de {days_late} jours. Sans règlement rapide, "
            f"le dossier sera transmis à notre service de recouvrement."
        )
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5;max-width:640px">
  <p style="margin:0 0 16px 0">Bonjour,</p>
  <p style="margin:0 0 16px 0">{lead}</p>
  <p style="margin:0 0 16px 0">
    Vous trouverez la facture en pièce jointe.
  </p>
  <p style="margin:0 0 6px 0"><strong>Modes de paiement acceptés :</strong></p>
  <ul style="margin:0 0 16px 18px;padding:0">
    <li><strong>Dépôt direct</strong> — Horizon Services Immobiliers,
        Institution 815, Transit 92004, Compte 0935973</li>
    <li><strong>Virement Interac</strong> à
        <a href="mailto:admin@immohorizon.com">admin@immohorizon.com</a></li>
  </ul>
  <p style="margin:0 0 16px 0;color:#555;font-size:13px">
    Tout retard de paiement après l'échéance est facturé à 2 % par mois
    (24 % annuel) selon nos conditions générales.
  </p>
  <p style="margin:16px 0 0 0">
    Si le paiement a déjà été fait, ignorez simplement ce courriel —
    la base sera mise à jour sous peu.
  </p>
  <p style="margin:24px 0 0 0;color:#555;font-size:12px">
    Horizon Services Immobiliers<br>
    RBQ 5868-5991-01<br>
    info@immohorizon.com
  </p>
</div>
"""


async def _client_for(db, client_id: Optional[int]) -> Optional[Client]:
    if not client_id:
        return None
    return (
        await db.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()


async def _compute_balance(db, fa: Facture) -> float:
    """Calcule le solde dû d'une facture en LIVE :
    - subtotal = somme des items (qty × unit_price) ou it.total si présent
    - total TTC = subtotal × 1,14975 (TPS 5 % + TVQ 9,975 %)
    - balance = total TTC − somme des paiements

    On ne se fie PAS au champ `Facture.total` qui peut être 0/null si
    les items ont été ajoutés sans recalculer la facture."""
    from sqlalchemy import func as _func

    items = (
        await db.execute(
            select(FactureItem).where(FactureItem.facture_id == fa.id)
        )
    ).scalars().all()
    subtotal = 0.0
    for it in items:
        if it.total is not None:
            subtotal += float(it.total)
        else:
            subtotal += float(it.quantity) * float(it.unit_price)
    total_ttc = round(subtotal * 1.14975, 2)

    # Si le champ Facture.total est plus précis (taxes pré-calculées
    # avec règles TPS/TVQ par item), on le préfère. Sinon, fallback
    # sur le calcul live.
    if fa.total is not None and float(fa.total) > 0:
        total_ttc = float(fa.total)

    paid = float(
        (
            await db.execute(
                select(_func.coalesce(_func.sum(Payment.amount), 0)).where(
                    Payment.facture_id == fa.id
                )
            )
        ).scalar_one()
        or 0
    )
    balance = round(max(0.0, total_ttc - paid), 2)
    return balance


async def run() -> dict:
    """Walk all unpaid factures, flip overdue and send the right reminder."""
    from app.services.automation_state import is_automation_enabled
    if not await is_automation_enabled("facture_reminders"):
        return {"skipped": "disabled"}
    mailer = get_mailer()
    now = datetime.now(timezone.utc)
    flipped_overdue = 0
    sent = 0
    skipped_no_mail = 0

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Facture).where(
                    Facture.status.in_(
                        [FactureStatus.SENT.value, FactureStatus.OVERDUE.value]
                    )
                )
            )
        ).scalars().all()

        for fa in rows:
            if fa.due_at is None:
                continue

            days_overdue = (now - fa.due_at).days
            if days_overdue < 1:
                continue

            # Flip status to overdue the first time we notice.
            if fa.status == FactureStatus.SENT.value:
                fa.status = FactureStatus.OVERDUE.value
                flipped_overdue += 1

            # Cadence : un rappel tous les 4 jours tant que la facture
            # est impayée. `next_reminder_at` (réglable à la main sur la
            # fiche) a priorité ; sinon on calcule depuis le dernier
            # rappel — ou l'échéance pour le tout premier.
            base = fa.last_reminder_at or fa.due_at
            due_next = fa.next_reminder_at or (
                base + timedelta(days=REMINDER_INTERVAL_DAYS)
            )
            if now < due_next:
                continue

            count = fa.reminder_count or 0
            tone = (
                "friendly"
                if count == 0
                else "firm"
                if count == 1
                else "final"
            )

            client = await _client_for(db, fa.client_id)
            to_email = client.email if client else None
            if not to_email:
                skipped_no_mail += 1
                # Still mark the reminder as "attempted" so we don't loop
                # on it every day with no target.
                fa.reminder_count = count + 1
                fa.last_reminder_at = now
                fa.next_reminder_at = now + timedelta(
                    days=REMINDER_INTERVAL_DAYS
                )
                # Persiste tout de suite : si le job plante plus loin, on ne
                # re-traitera pas cette facture au prochain run.
                await db.commit()
                continue

            if not mailer.ready:
                log.warning("Mailer not ready — skipping %s", fa.reference)
                break

            # Generate PDF inline and attach.
            try:
                rendered = await render_facture_pdf(db, fa.id)
                pdf_bytes = rendered[1] if rendered else b""
                attachments = (
                    [
                        EmailAttachment(
                            name=f"facture-{fa.reference}.pdf",
                            content_bytes=pdf_bytes,
                            content_type="application/pdf",
                        )
                    ]
                    if pdf_bytes
                    else None
                )
                # Solde dû LIVE (items + taxes − paiements) — évite
                # d'envoyer « 0,00 $ » quand fa.total n'a pas été
                # recalculé après l'ajout d'items.
                total_val = await _compute_balance(db, fa)
                await mailer.send(
                    to=[to_email],
                    # Pas de CC interne — le rappel doit ressembler
                    # à un courriel reçu directement par le client,
                    # pas à un envoi d'équipe en copie.
                    subject=(
                        f"{_SUBJECT_PREFIX[tone]} — Facture {fa.reference}"
                    ),
                    html_body=_body_html(
                        tone, fa.reference, total_val, days_overdue
                    ),
                    attachments=attachments,
                    reply_to=settings.mail_from_email,
                )
                sent += 1
                fa.reminder_count = count + 1
                fa.last_reminder_at = now
                fa.next_reminder_at = now + timedelta(
                    days=REMINDER_INTERVAL_DAYS
                )
                # Commit immédiat APRÈS l'envoi : le rappel envoyé est
                # enregistré sur-le-champ. Si le job plante sur une facture
                # suivante, on ne renvoie pas ce rappel-ci au prochain run
                # (évite les doubles courriels sur échec partiel).
                await db.commit()
            except Exception as exc:
                log.exception("Reminder send failed for %s: %s", fa.reference, exc)

        await db.commit()

    return {
        "flipped_to_overdue": flipped_overdue,
        "reminders_sent": sent,
        "skipped_no_client_email": skipped_no_mail,
    }


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = asyncio.run(run())
    log.info("facture_reminders: %s", result)


if __name__ == "__main__":
    main()
