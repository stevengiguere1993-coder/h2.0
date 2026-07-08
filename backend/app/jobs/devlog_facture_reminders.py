"""Daily cron: relances automatiques des factures Dev logiciel.

Lance une fois par jour. Pour chaque ``DevlogInvoice`` au statut
``envoyee`` dont la ``due_date`` est dépassée, on calcule le nombre
de jours de retard et on envoie un rappel courriel au client. Le
ton et la cadence escaladent par paliers :

- J+1 à J+6 : 1er rappel courtois (un envoi toutes les 24 h)
- J+7 à J+13 : 2e rappel ferme (un envoi toutes les 48 h)
- J+14 à J+29 : 3e rappel sérieux (un envoi par semaine)
- J+30+ : escalade unique + notification interne admin, puis arrêt
  des envois automatiques

Pour éviter le spam, on stocke ``last_reminder_sent_at`` et
``reminder_count`` sur la facture (colonnes ajoutées via
``additive_columns`` dans ``app.db.session``). Chaque palier a son
propre délai minimum entre deux relances.

Usage (Render cron) :
    python -m app.jobs.devlog_facture_reminders

Pattern calqué sur ``app.jobs.facture_reminders`` (Construction).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.devlog_client import DevlogClient
from app.models.devlog_invoice import DevlogInvoice
from app.models.devlog_invoice_item import DevlogInvoiceItem
from app.services.audit import log_action
from app.services.devlog_invoice_pdf import (
    BUYER_ENTITY_NAME,
    compute_invoice_totals,
    generate_invoice_pdf,
)
from app.services.public_links import public_base
from app.services.notifications import notify_role


log = logging.getLogger(__name__)


# Escalade en quatre paliers. Pour chaque palier on définit :
#  - ``min_days`` / ``max_days`` : fenêtre de jours de retard
#  - ``interval_days`` : délai minimum entre deux relances
#  - ``tone`` : clé du sujet/corps de l'email
TIER_COURTEOUS = {
    "min_days": 1,
    "max_days": 6,
    "interval_days": 1,
    "tone": "courteous",
}
TIER_FIRM = {
    "min_days": 7,
    "max_days": 13,
    "interval_days": 2,
    "tone": "firm",
}
TIER_SERIOUS = {
    "min_days": 14,
    "max_days": 29,
    "interval_days": 7,
    "tone": "serious",
}
TIER_ESCALATION = {
    "min_days": 30,
    "max_days": None,  # ouvert à droite
    "interval_days": None,  # envoi unique
    "tone": "escalation",
}

_TIERS = (TIER_COURTEOUS, TIER_FIRM, TIER_SERIOUS, TIER_ESCALATION)


_SUBJECT_BY_TONE = {
    "courteous": "Petit rappel — Facture {label}",
    "firm": "Rappel — Facture {label} en retard",
    "serious": "Important — Facture {label} en retard significatif",
    "escalation": "Dernier rappel — Facture {label} avant recouvrement",
}


def _fmt_money(n: float) -> str:
    """Format canadien : « 1 234,56 $ »."""
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} $"


def _fmt_date(d) -> str:
    if d is None:
        return "—"
    try:
        return d.strftime("%Y-%m-%d")
    except Exception:
        return str(d)


def _tier_for(days_late: int) -> Optional[dict]:
    """Retourne le palier correspondant aux jours de retard."""
    for tier in _TIERS:
        max_d = tier["max_days"]
        if days_late >= tier["min_days"] and (
            max_d is None or days_late <= max_d
        ):
            return tier
    return None


def _email_body(
    tone: str,
    invoice_label: str,
    total_ttc: float,
    due_date,
    days_late: int,
    pay_url: str,
    client_name: Optional[str],
) -> str:
    salutation = (
        f"Bonjour {client_name}," if client_name else "Bonjour,"
    )
    pluriel = "s" if days_late > 1 else ""
    if tone == "courteous":
        lead = (
            f"Petit rappel amical : la facture <strong>{invoice_label}"
            f"</strong> (montant <strong>{_fmt_money(total_ttc)}</strong>, "
            f"échue le {_fmt_date(due_date)}) est en retard de "
            f"{days_late} jour{pluriel}. Si le paiement a déjà été "
            f"fait, merci d'ignorer ce courriel."
        )
    elif tone == "firm":
        lead = (
            f"La facture <strong>{invoice_label}</strong> "
            f"(<strong>{_fmt_money(total_ttc)}</strong>, échue le "
            f"{_fmt_date(due_date)}) est maintenant en retard depuis "
            f"{days_late} jour{pluriel}. Merci de procéder au paiement "
            f"dans les meilleurs délais."
        )
    elif tone == "serious":
        lead = (
            f"Votre facture <strong>{invoice_label}</strong> "
            f"(<strong>{_fmt_money(total_ttc)}</strong>, échue le "
            f"{_fmt_date(due_date)}) est en retard significatif depuis "
            f"{days_late} jour{pluriel}. Si vous rencontrez une "
            f"difficulté, contactez-nous au plus vite pour convenir "
            f"d'un arrangement."
        )
    else:  # escalation
        lead = (
            f"Dernier rappel avant transfert au recouvrement : la "
            f"facture <strong>{invoice_label}</strong> "
            f"(<strong>{_fmt_money(total_ttc)}</strong>) est en retard "
            f"de {days_late} jour{pluriel}. Merci de nous contacter "
            f"immédiatement pour régulariser la situation."
        )
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.55;max-width:620px">
  <p style="margin:0 0 16px 0">{salutation}</p>
  <p style="margin:0 0 16px 0">{lead}</p>
  <p style="margin:0 0 16px 0">
    Vous pouvez consulter la facture et son détail en ligne :
  </p>
  <p style="margin:20px 0 6px 0">
    <a href="{pay_url}"
       style="display:inline-block;background:#1e40af;color:#fff;
              padding:14px 24px;border-radius:8px;font-weight:bold;
              text-decoration:none">Consulter la facture</a>
  </p>
  <p style="margin:8px 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {pay_url}
  </p>
  <p style="margin:0 0 16px 0">
    Modalités acceptées : virement bancaire (Interac e-Transfer
    à comptabilite@immohorizon.com) ou chèque libellé à
    « {BUYER_ENTITY_NAME} inc. ».
  </p>
  <p style="margin:24px 0 4px 0;color:#555;font-size:12px">
    Cordialement,<br/>
    {BUYER_ENTITY_NAME} &middot; Pôle Développement logiciel &middot;
    immohorizon.com
  </p>
</div>
"""


async def _load_client(
    db, client_id: Optional[int]
) -> Optional[DevlogClient]:
    if client_id is None:
        return None
    return (
        await db.execute(
            select(DevlogClient).where(DevlogClient.id == client_id)
        )
    ).scalar_one_or_none()


async def _load_items(db, invoice_id: int) -> list[DevlogInvoiceItem]:
    return list(
        (
            await db.execute(
                select(DevlogInvoiceItem)
                .where(DevlogInvoiceItem.invoice_id == invoice_id)
                .order_by(
                    DevlogInvoiceItem.position.asc(),
                    DevlogInvoiceItem.id.asc(),
                )
            )
        ).scalars().all()
    )


def _should_send(
    tier: dict, last_sent_at: Optional[datetime], now: datetime
) -> bool:
    """Décide si on envoie une relance pour ce palier.

    - Si jamais relancée, on envoie.
    - Palier escalation : envoi unique (si jamais envoyée → oui,
      sinon → non, et on coupe les envois auto).
    - Autres paliers : envoi si l'intervalle minimum est passé.
    """
    if last_sent_at is None:
        return True
    if tier["interval_days"] is None:
        # Palier escalation : un seul envoi automatique. Si on a déjà
        # relancé au moins une fois (peu importe le palier), pas de
        # nouvel envoi auto — l'équipe prend le relais manuellement.
        return False
    interval = timedelta(days=int(tier["interval_days"]))
    return (now - last_sent_at) >= interval


async def run() -> dict:
    """Parcourt les factures envoyées en retard et déclenche les
    relances qui sont dues d'après leur palier."""
    from app.services.automation_state import is_automation_enabled
    if not await is_automation_enabled("devlog_facture_reminders"):
        return {"skipped": "disabled"}
    mailer = get_mailer()
    now = datetime.now(timezone.utc)
    today = now.date()
    sent = 0
    skipped_no_mail = 0
    escalations = 0

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(DevlogInvoice).where(
                    DevlogInvoice.status == "envoyee"
                )
            )
        ).scalars().all()

        for inv in rows:
            due: Optional[date] = inv.due_date
            if due is None:
                continue
            days_late = (today - due).days
            if days_late < 1:
                continue

            tier = _tier_for(days_late)
            if tier is None:
                continue

            last_sent = getattr(inv, "last_reminder_sent_at", None)
            if not _should_send(tier, last_sent, now):
                continue

            # Sans email client, on ne peut rien faire. On ne touche
            # PAS au compteur — la facture reste éligible pour quand
            # on saisira un email.
            client = await _load_client(db, inv.client_id)
            to_email = (
                (client.email or "").strip() if client is not None else ""
            )
            if not to_email:
                skipped_no_mail += 1
                continue

            if not mailer.ready:
                log.warning(
                    "Mailer non configuré — arrêt du job pour %s",
                    inv.id,
                )
                break

            # Charge items + recalcule le total TTC live (le champ
            # ``amount`` peut être HT ou stale selon l'historique).
            items = await _load_items(db, inv.id)
            totals = compute_invoice_totals(items)
            total_ttc = totals.get("total") or float(inv.amount or 0)

            invoice_label = inv.number or f"#{inv.id}"
            pay_url = (
                f"{public_base()}/devlog/pay-invoice/"
                f"{inv.signature_token or ''}"
            )
            subject = _SUBJECT_BY_TONE[tier["tone"]].format(
                label=invoice_label
            )
            body = _email_body(
                tone=tier["tone"],
                invoice_label=invoice_label,
                total_ttc=total_ttc,
                due_date=due,
                days_late=days_late,
                pay_url=pay_url,
                client_name=client.name if client is not None else None,
            )

            # Attache le PDF (best-effort — si la génération échoue
            # on envoie quand même le mail texte seul).
            attachments = None
            try:
                pdf_bytes = await generate_invoice_pdf(db, inv.id)
                if pdf_bytes:
                    attachments = [
                        EmailAttachment(
                            name=f"facture-{invoice_label}.pdf",
                            content_bytes=pdf_bytes,
                            content_type="application/pdf",
                        )
                    ]
            except Exception as exc:  # pragma: no cover - best effort
                log.warning(
                    "PDF gen failed for devlog invoice %s: %s",
                    inv.id,
                    exc,
                )

            try:
                await mailer.send(
                    to=[to_email],
                    subject=subject,
                    html_body=body,
                    reply_to=mailer.sender,
                    attachments=attachments,
                )
            except Exception as exc:
                log.exception(
                    "Reminder send failed for devlog invoice %s: %s",
                    inv.id,
                    exc,
                )
                continue

            sent += 1
            inv.reminder_count = (inv.reminder_count or 0) + 1
            inv.last_reminder_sent_at = now

            await log_action(
                db,
                user=None,
                action="devlog_invoice.reminder_sent",
                entity_type="devlog_invoice",
                entity_id=inv.id,
                details={
                    "tier": tier["tone"],
                    "days_late": days_late,
                    "to": to_email,
                    "reminder_count": inv.reminder_count,
                },
            )

            # Palier escalation → notif interne urgente aux admins.
            if tier["tone"] == "escalation":
                escalations += 1
                client_label = (
                    (client.company or client.name)
                    if client is not None
                    else "client inconnu"
                )
                try:
                    await notify_role(
                        db,
                        min_role="admin",
                        kind="devlog_invoice.overdue_critical",
                        title=(
                            f"Facture devlog en retard critique : "
                            f"{invoice_label}"
                        ),
                        body=(
                            f"{client_label} — {days_late} jours de "
                            f"retard, montant {_fmt_money(total_ttc)}. "
                            f"Dernière relance auto envoyée, prendre "
                            f"le relais manuellement."
                        ),
                        href=f"/dev-logiciel/facturation/{inv.id}",
                    )
                except Exception as exc:  # pragma: no cover
                    log.warning(
                        "notify_role failed for invoice %s: %s",
                        inv.id,
                        exc,
                    )
                await log_action(
                    db,
                    user=None,
                    action="devlog_invoice.overdue_critical",
                    entity_type="devlog_invoice",
                    entity_id=inv.id,
                    details={
                        "days_late": days_late,
                        "client_name": (
                            client.name if client is not None else None
                        ),
                        "amount": total_ttc,
                    },
                )

        await db.commit()

    return {
        "reminders_sent": sent,
        "escalations": escalations,
        "skipped_no_client_email": skipped_no_mail,
    }


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = asyncio.run(run())
    log.info("devlog_facture_reminders: %s", result)


if __name__ == "__main__":
    main()
