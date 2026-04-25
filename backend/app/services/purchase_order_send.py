"""Send a PurchaseOrder to its assigned employee by email.

Le PO est généré comme un courriel HTML formaté que l'employé reçoit
sur son téléphone : numéro PO, fournisseur, projet, montant max
autorisé, mode de paiement, description du matériel.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import get_mailer
from app.models.employe import Employe
from app.models.fournisseur import Fournisseur
from app.models.project import Project
from app.models.purchase_order import PurchaseOrder, PurchaseOrderStatus


log = logging.getLogger(__name__)


class PurchaseOrderSendError(Exception):
    pass


_PAYMENT_LABELS = {
    "bill_to_pay": "Sur compte fournisseur (à payer plus tard)",
    "cheque_horizon": "Compte chèque Horizon",
    "cc_steven": "CC Horizon Steven Giguère",
    "cc_michael": "CC Horizon Michael Villiard",
    "cc_olivier": "CC Horizon Olivier Therrien",
    "cc_christian": "CC Horizon Christian Villiard",
}


async def send_purchase_order(
    db: AsyncSession,
    po_id: int,
    *,
    extra_message: Optional[str] = None,
) -> PurchaseOrder:
    po = (
        await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
    ).scalar_one_or_none()
    if po is None:
        raise PurchaseOrderSendError(f"PO {po_id} introuvable")
    if not po.assigned_employe_id:
        raise PurchaseOrderSendError(
            "Aucun employé assigné — choisis qui doit aller "
            "chercher la marchandise."
        )

    employe = (
        await db.execute(
            select(Employe).where(Employe.id == po.assigned_employe_id)
        )
    ).scalar_one_or_none()
    if employe is None or not (employe.email or "").strip():
        raise PurchaseOrderSendError(
            "L'employé assigné n'a pas d'adresse courriel."
        )

    fournisseur: Optional[Fournisseur] = None
    if po.fournisseur_id:
        fournisseur = (
            await db.execute(
                select(Fournisseur).where(Fournisseur.id == po.fournisseur_id)
            )
        ).scalar_one_or_none()
    project: Optional[Project] = None
    if po.project_id:
        project = (
            await db.execute(
                select(Project).where(Project.id == po.project_id)
            )
        ).scalar_one_or_none()

    payment_label = _PAYMENT_LABELS.get(
        po.payment_method or "bill_to_pay",
        po.payment_method or "—",
    )
    amount_str = (
        f"{float(po.amount_max):,.2f} $".replace(",", " ").replace(".", ",")
        if po.amount_max
        else "(montant à définir)"
    )

    fournisseur_line = (fournisseur.name if fournisseur else "—")
    if fournisseur and fournisseur.phone:
        fournisseur_line = f"{fournisseur_line} · {fournisseur.phone}"

    project_line = project.name if project else "Non rattaché — frais généraux"
    if project and project.address:
        project_line = (
            f"{project_line}<br/>"
            f'<span style="color:#888;font-size:12px">{project.address}</span>'
        )

    note_block = ""
    if extra_message:
        note_block = (
            '<h3 style="color: #b8860b; margin: 18px 0 6px;">'
            "Note du bureau</h3>"
            '<p style="white-space: pre-wrap; margin: 0 0 18px;">'
            f"{extra_message}</p>"
        )

    description_text = po.description or "(à coordonner avec le bureau)"

    body_html = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #111;">
  <h2 style="color: #b8860b; margin: 0 0 8px;">Bon de commande {po.reference}</h2>
  <p style="color: #555; margin: 0 0 18px;">
    Salut {employe.full_name},<br/>
    Voici les détails de la commande à passer chez le fournisseur.
  </p>

  <table style="border-collapse: collapse; margin-bottom: 18px;">
    <tr>
      <td style="padding: 6px 12px 6px 0; color: #666;">Numéro PO</td>
      <td style="padding: 6px 0; font-weight: bold;">{po.reference}</td>
    </tr>
    <tr>
      <td style="padding: 6px 12px 6px 0; color: #666;">Fournisseur</td>
      <td style="padding: 6px 0;">{fournisseur_line}</td>
    </tr>
    <tr>
      <td style="padding: 6px 12px 6px 0; color: #666;">Projet</td>
      <td style="padding: 6px 0;">{project_line}</td>
    </tr>
    <tr>
      <td style="padding: 6px 12px 6px 0; color: #666;">Montant max autorisé</td>
      <td style="padding: 6px 0; font-weight: bold; color: #b8860b;">{amount_str}</td>
    </tr>
    <tr>
      <td style="padding: 6px 12px 6px 0; color: #666;">Mode de paiement</td>
      <td style="padding: 6px 0;">{payment_label}</td>
    </tr>
  </table>

  <h3 style="color: #b8860b; margin: 18px 0 6px;">Matériel</h3>
  <p style="white-space: pre-wrap; margin: 0 0 18px;">{description_text}</p>

  {note_block}

  <div style="margin: 20px 0; padding: 14px 16px; background: #fdf6e3; border-left: 4px solid #b8860b; border-radius: 4px;">
    <p style="margin: 0; color: #555; font-size: 13px;">
      <strong>Important :</strong> donne le numéro PO {po.reference} à la caisse.
      Garde le reçu et envoie-le au bureau (photo / texte) pour qu'on puisse
      réconcilier l'achat.
    </p>
  </div>

  <p style="color: #888; font-size: 12px; margin-top: 24px;">
    Envoyé automatiquement par Horizon Services Immobiliers · h2.0
  </p>
</div>
"""

    mailer = get_mailer()
    await mailer.send(
        to=[employe.email],
        subject=(
            f"PO {po.reference} — "
            f"{(fournisseur.name if fournisseur else 'Achat à passer')}"
        ),
        html_body=body_html,
    )

    now = datetime.now(timezone.utc)
    if po.status == PurchaseOrderStatus.DRAFT.value:
        po.status = PurchaseOrderStatus.SENT.value
        po.sent_at = now
    await db.flush()
    await db.refresh(po)
    log.info("PO %s envoyé à %s", po.reference, employe.email)
    return po
