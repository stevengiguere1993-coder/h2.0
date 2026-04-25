"""Send a PO (Achat) to the assigned employee by email.

Le PO est généré avec les infos clés que l'employé doit avoir au
moment d'aller au magasin :
  - Numéro PO (à donner à la caisse)
  - Fournisseur (nom + téléphone si dispo)
  - Projet (nom + adresse)
  - Montant max autorisé
  - Description / liste de matériel
  - Mode de paiement (carte de crédit Steven, etc.)

Pas de PDF lourd : un courriel HTML formaté qui se lit bien sur le
mobile du foreman.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.email_graph import get_mailer
from app.models.achat import Achat, AchatStatus
from app.models.employe import Employe
from app.models.fournisseur import Fournisseur
from app.models.project import Project


log = logging.getLogger(__name__)


class AchatSendError(Exception):
    pass


_PAYMENT_LABELS = {
    "bill_to_pay": "Sur compte fournisseur (à payer plus tard)",
    "cheque_horizon": "Compte chèque Horizon",
    "cc_steven": "CC Horizon Steven Giguère",
    "cc_michael": "CC Horizon Michael Villiard",
    "cc_olivier": "CC Horizon Olivier Therrien",
    "cc_christian": "CC Horizon Christian Villiard",
}


async def send_achat_po(
    db: AsyncSession,
    achat_id: int,
    *,
    extra_message: Optional[str] = None,
) -> Achat:
    achat = (
        await db.execute(select(Achat).where(Achat.id == achat_id))
    ).scalar_one_or_none()
    if achat is None:
        raise AchatSendError(f"Achat {achat_id} introuvable")
    if not achat.assigned_employe_id:
        raise AchatSendError(
            "Aucun employé assigné — choisis qui doit aller "
            "chercher la marchandise."
        )

    employe = (
        await db.execute(
            select(Employe).where(Employe.id == achat.assigned_employe_id)
        )
    ).scalar_one_or_none()
    if employe is None or not (employe.email or "").strip():
        raise AchatSendError(
            "L'employé assigné n'a pas d'adresse courriel."
        )

    fournisseur: Optional[Fournisseur] = None
    if achat.fournisseur_id:
        fournisseur = (
            await db.execute(
                select(Fournisseur).where(Fournisseur.id == achat.fournisseur_id)
            )
        ).scalar_one_or_none()
    project: Optional[Project] = None
    if achat.project_id:
        project = (
            await db.execute(
                select(Project).where(Project.id == achat.project_id)
            )
        ).scalar_one_or_none()

    payment_label = _PAYMENT_LABELS.get(
        achat.payment_method or "operations",
        achat.payment_method or "—",
    )

    amount_str = (
        f"{float(achat.amount):,.2f} $".replace(",", " ").replace(".", ",")
        if achat.amount
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

    description_text = (
        achat.description or "(à coordonner avec le bureau)"
    )

    body_html = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #111;">
  <h2 style="color: #b8860b; margin: 0 0 8px;">Bon de commande {achat.reference}</h2>
  <p style="color: #555; margin: 0 0 18px;">
    Salut {employe.full_name},<br/>
    Voici les détails de la commande à passer chez le fournisseur.
  </p>

  <table style="border-collapse: collapse; margin-bottom: 18px;">
    <tr>
      <td style="padding: 6px 12px 6px 0; color: #666;">Numéro PO</td>
      <td style="padding: 6px 0; font-weight: bold;">{achat.reference}</td>
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
      <strong>Important :</strong> donne le numéro PO {achat.reference} à la caisse.
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
        subject=f"PO {achat.reference} — {(fournisseur.name if fournisseur else 'Achat à passer')}",
        html_body=body_html,
    )

    # Avance le statut → ordered (PO envoyé) si on était encore en
    # draft. Idempotent : un renvoi reste en ordered.
    now = datetime.now(timezone.utc)
    if achat.status == AchatStatus.DRAFT.value:
        achat.status = AchatStatus.ORDERED.value
        achat.ordered_at = now
    await db.flush()
    await db.refresh(achat)
    log.info("PO %s envoyé à %s", achat.reference, employe.email)
    return achat


# Used to silence unused-import warning when settings is referenced
# only conditionally (e.g. mocking in tests).
_ = settings
