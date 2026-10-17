"""Envoi par email d'une facture du pôle Dev Logiciel au client.

Pattern calqué sur ``app.services.devlog_soumission_send`` (PR #473) :

- Génère / récupère un ``signature_token`` opaque (pour la page
  publique de consultation)
- Génère un numéro séquentiel ``INV-YYYY-NNNNN`` via
  ``app.services.numbering.next_facture_number`` si la facture n'en
  a pas encore
- Définit ``due_date`` (par défaut +30 jours) si absente
- Rend le PDF
- Envoie via Graph un email court au client avec le lien public
  ``/devlog/pay-invoice/{token}`` et le PDF en pièce jointe
- Best-effort : si Graph échoue, on log un warning et on ne fait pas
  échouer l'envoi (la facture passe quand même en ``envoyee``)
- Bloque l'envoi d'une facture déjà ``payee`` ou ``annulee``.
"""

from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.devlog_client import DevlogClient
from app.models.devlog_invoice import DevlogInvoice
from app.models.devlog_invoice_item import DevlogInvoiceItem
from app.services.devlog_invoice_pdf import (
    BUYER_ENTITY_NAME,
    compute_invoice_totals,
    generate_invoice_pdf,
)
from app.services.numbering import next_facture_number
from app.services.public_links import public_base


log = logging.getLogger(__name__)


class DevlogInvoiceSendError(Exception):
    pass


async def _load_client(
    db: AsyncSession, client_id: Optional[int]
) -> Optional[DevlogClient]:
    if client_id is None:
        return None
    return (
        await db.execute(
            select(DevlogClient).where(DevlogClient.id == client_id)
        )
    ).scalar_one_or_none()


async def _load_items(
    db: AsyncSession, invoice_id: int
) -> list[DevlogInvoiceItem]:
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


def _fmt_money(n: float) -> str:
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


def _client_body(
    invoice: DevlogInvoice,
    client: Optional[DevlogClient],
    pay_url: str,
    total: float,
) -> str:
    """Email court au client."""
    salutation = (
        f"Bonjour {client.name},"
        if client is not None and client.name
        else "Bonjour,"
    )
    invoice_label = invoice.number or f"#{invoice.id}"
    due_text = (
        f"dûe le {_fmt_date(invoice.due_date)}"
        if invoice.due_date
        else "payable sous 30 jours"
    )
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.55;max-width:620px">
  <p style="margin:0 0 16px 0">{salutation}</p>
  <p style="margin:0 0 16px 0">
    Vous trouverez ci-joint la facture <strong>{invoice_label}</strong>
    pour un montant de <strong>{_fmt_money(total)}</strong> ({due_text}).
  </p>
  <p style="margin:0 0 16px 0">
    Vous pouvez aussi la consulter en ligne et télécharger le PDF
    en cliquant sur le bouton ci-dessous :
  </p>
  <p style="margin:20px 0 6px 0">
    <a href="{pay_url}"
       style="display:inline-block;background:#1e40af;color:#fff;
              padding:14px 24px;border-radius:8px;font-weight:bold;
              text-decoration:none">Consulter la facture en ligne</a>
  </p>
  <p style="margin:8px 0 16px 0;font-size:12px;color:#555">
    Ou copiez ce lien : {pay_url}
  </p>
  <p style="margin:0 0 16px 0">
    Modalités acceptées : virement bancaire (Interac e-Transfer) ou
    chèque libellé à <em>{BUYER_ENTITY_NAME} inc.</em>
  </p>
  <p style="margin:24px 0 4px 0;color:#555;font-size:12px">
    Cordialement,<br/>
    {BUYER_ENTITY_NAME} &middot; Pôle Développement logiciel &middot;
    immohorizon.com
  </p>
</div>
"""


async def _ensure_invoice_metadata(
    db: AsyncSession, invoice: DevlogInvoice
) -> None:
    """Avant l'envoi, attribue le numéro, l'échéance et le token si
    absents. Le numéro suit le format ``INV-YYYY-NNNNN`` (compteur
    atomique partagé avec les factures de construction)."""
    changed = False
    if not (invoice.number or "").strip():
        raw = await next_facture_number(db)
        year = (invoice.issued_date or datetime.utcnow().date()).year
        try:
            n = int(raw)
        except (TypeError, ValueError):
            n = 0
        invoice.number = f"INV-{year}-{n:05d}"
        changed = True
    if invoice.issued_date is None:
        invoice.issued_date = datetime.utcnow().date()
        changed = True
    if invoice.due_date is None:
        # Défaut : 30 jours après l'émission.
        base: date = invoice.issued_date or datetime.utcnow().date()
        invoice.due_date = base + timedelta(days=30)
        changed = True
    if not getattr(invoice, "signature_token", None):
        invoice.signature_token = secrets.token_urlsafe(32)
        changed = True
    if changed:
        await db.flush()


async def send_invoice_email(
    db: AsyncSession, invoice_id: int
) -> DevlogInvoice:
    """Envoi de la facture au client.

    - Vérifie que le statut autorise l'envoi (``brouillon`` ou
      ``envoyee`` — renvoi possible si le client a perdu l'email)
    - Génère le numéro / l'échéance / le token si absents
    - Génère le PDF
    - Envoie via Graph (best-effort)
    - Passe ``status=envoyee`` et ``sent_at=now()``
    """
    invoice = (
        await db.execute(
            select(DevlogInvoice).where(DevlogInvoice.id == invoice_id)
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise DevlogInvoiceSendError(
            f"Facture {invoice_id} introuvable."
        )
    if invoice.status not in ("brouillon", "envoyee"):
        raise DevlogInvoiceSendError(
            f"Facture au statut « {invoice.status} » — envoi impossible."
        )

    client = await _load_client(db, invoice.client_id)
    if client is None or not (client.email or "").strip():
        raise DevlogInvoiceSendError(
            "Adresse courriel du client manquante — impossible "
            "d'envoyer la facture."
        )

    await _ensure_invoice_metadata(db, invoice)

    items = await _load_items(db, invoice.id)
    totals = compute_invoice_totals(items)

    pdf_bytes = await generate_invoice_pdf(db, invoice_id)
    invoice_label = invoice.number or f"facture-{invoice.id}"
    attachment = EmailAttachment(
        name=f"facture-{invoice_label}.pdf",
        content_bytes=pdf_bytes,
        content_type="application/pdf",
    )

    pay_url = (
        f"{public_base()}/devlog/pay-invoice/{invoice.signature_token}"
    )
    subject = (
        f"Facture {invoice_label} — {BUYER_ENTITY_NAME}"
    )
    body = _client_body(invoice, client, pay_url, totals["total"])

    mailer = get_mailer()
    if mailer.ready:
        try:
            await mailer.send(
                to=[client.email],
                subject=subject,
                html_body=body,
                reply_to=mailer.sender,
                attachments=[attachment],
            )
        except Exception as exc:  # best-effort
            log.warning(
                "Graph send failed for devlog invoice %s: %s",
                invoice.id,
                exc,
            )
    else:
        log.warning(
            "Graph mailer non configuré — facture %s marquée "
            "comme envoyée sans courriel.",
            invoice.id,
        )

    invoice.status = "envoyee"
    invoice.sent_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(invoice)
    return invoice
