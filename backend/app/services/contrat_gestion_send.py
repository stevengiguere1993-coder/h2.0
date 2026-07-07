"""Envois courriel du contrat de gestion (Microsoft Graph) — 2 signatures.

Flux :
1. `send_to_mandataire` : le contrat part d'abord au signataire MGV
   (Mandataire) pour la 1re signature.
2. `send_to_mandant` : une fois MGV signé, relais automatique au Mandant
   pour la 2e signature.
3. `email_signed_to_both` : une fois les deux signés, le PDF signé final
   est envoyé par courriel aux deux parties.

Patron calqué sur `nda_send`.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_graph import EmailAttachment, get_mailer
from app.models.contrat_gestion import ContratGestion, ContratGestionStatus
from app.services.contrat_gestion_pdf import (
    contrat_pdf_filename,
    render_contrat_pdf,
)
from app.services.contrat_gestion_service import resolve_body_markdown
from app.services.contrat_gestion_template import MANDATAIRE_NOM
from app.services.public_links import public_base

log = logging.getLogger(__name__)


class ContratGestionSendError(Exception):
    pass


def _sign_url(token: str) -> str:
    return f"{public_base()}/sign-contrat-gestion/{token}"


def _shell(inner: str) -> str:
    return (
        '<div style="font-family:Helvetica,Arial,sans-serif;color:#111;'
        'line-height:1.55;max-width:620px">' + inner +
        '<p style="margin:24px 0 4px 0;color:#555;font-size:12px">'
        f"{MANDATAIRE_NOM} &middot; immohorizon.com</p></div>"
    )


def _cta(url: str, label: str) -> str:
    return (
        f'<p style="margin:20px 0 6px 0"><a href="{url}" '
        'style="display:inline-block;background:#0f766e;color:#fff;'
        'padding:14px 24px;border-radius:8px;font-weight:bold;'
        f'text-decoration:none">{label}</a></p>'
        f'<p style="margin:8px 0 16px 0;font-size:12px;color:#555">'
        f"Ou copiez ce lien : {url}</p>"
    )


def _mandataire_body(contrat: ContratGestion, url: str) -> str:
    who = (contrat.mandataire_nom or "").strip()
    salut = f"Bonjour {who}," if who else "Bonjour,"
    compagnie = (contrat.compagnie or "").strip()
    ref = f" avec <strong>{compagnie}</strong>" if compagnie else ""
    return _shell(
        f'<p style="margin:0 0 16px 0">{salut}</p>'
        f'<p style="margin:0 0 16px 0">Voici la <strong>convention de gestion '
        f"immobilière</strong>{ref}. À titre de Mandataire (MGV), veuillez la "
        "signer en premier ; elle sera ensuite transmise automatiquement au "
        "Mandant pour sa signature.</p>"
        + _cta(url, "Consulter et signer (Mandataire)")
        + '<p style="margin:0 0 16px 0">Une copie PDF est jointe à ce '
        "courriel.</p>"
    )


def _mandant_body(contrat: ContratGestion, url: str) -> str:
    who = (contrat.representant_nom or "").strip()
    salut = f"Bonjour {who}," if who else "Bonjour,"
    compagnie = (contrat.compagnie or "").strip()
    ref = f" pour <strong>{compagnie}</strong>" if compagnie else ""
    return _shell(
        f'<p style="margin:0 0 16px 0">{salut}</p>'
        f'<p style="margin:0 0 16px 0"><strong>{MANDATAIRE_NOM}</strong> a signé '
        f"la <strong>convention de gestion immobilière</strong>{ref}. Il ne "
        "reste que votre signature pour la finaliser.</p>"
        + _cta(url, "Consulter et signer la convention")
        + '<p style="margin:0 0 16px 0">Une copie PDF est jointe à ce '
        "courriel.</p>"
    )


def _final_body(contrat: ContratGestion) -> str:
    compagnie = (contrat.compagnie or "").strip()
    ref = f" ({compagnie})" if compagnie else ""
    return _shell(
        '<p style="margin:0 0 16px 0">Bonjour,</p>'
        f'<p style="margin:0 0 16px 0">La <strong>convention de gestion '
        f"immobilière</strong>{ref} est maintenant <strong>signée par les deux "
        "parties</strong>. Vous trouverez la version finale signée en pièce "
        "jointe à ce courriel, pour vos dossiers.</p>"
    )


async def _ensure(db: AsyncSession, contrat_id: int) -> ContratGestion:
    contrat = (
        await db.execute(
            select(ContratGestion).where(ContratGestion.id == contrat_id)
        )
    ).scalar_one_or_none()
    if contrat is None:
        raise ContratGestionSendError(f"Contrat {contrat_id} introuvable.")
    return contrat


def _mailer_or_raise():
    mailer = get_mailer()
    if not mailer.ready:
        raise ContratGestionSendError(
            "Microsoft Graph mailer non configuré (AZURE_* / MAIL_FROM_EMAIL)."
        )
    return mailer


async def _render_pdf(db: AsyncSession, contrat: ContratGestion) -> bytes:
    body_md = await resolve_body_markdown(db, contrat)
    try:
        return render_contrat_pdf(contrat, body_md)
    except Exception as exc:
        log.exception("Rendu PDF échoué pour contrat de gestion %s", contrat.id)
        raise ContratGestionSendError(
            f"Rendu du PDF de la convention échoué : {exc}"
        ) from exc


async def send_to_mandataire(db: AsyncSession, contrat_id: int) -> ContratGestion:
    """Étape 1 : envoie la convention au signataire MGV (Mandataire)."""
    contrat = await _ensure(db, contrat_id)
    if not (contrat.mandataire_courriel or "").strip():
        raise ContratGestionSendError("Courriel du signataire MGV manquant.")
    if not (contrat.mandant_courriel or "").strip():
        raise ContratGestionSendError("Courriel du Mandant manquant.")
    if not contrat.mandataire_signature_token:
        contrat.mandataire_signature_token = secrets.token_urlsafe(32)
        await db.flush()

    mailer = _mailer_or_raise()
    pdf_bytes = await _render_pdf(db, contrat)
    attachment = EmailAttachment(
        name=contrat_pdf_filename(contrat),
        content_bytes=pdf_bytes,
        content_type="application/pdf",
    )
    url = _sign_url(contrat.mandataire_signature_token)
    try:
        await mailer.send(
            to=[contrat.mandataire_courriel],
            subject=f"À signer (Mandataire) — Convention de gestion — {MANDATAIRE_NOM}",
            html_body=_mandataire_body(contrat, url),
            reply_to=mailer.sender,
            attachments=[attachment],
        )
    except Exception as exc:
        log.exception("Graph send (mandataire) failed for contrat %s", contrat.id)
        raise ContratGestionSendError(f"Envoi courriel échoué: {exc}") from exc

    contrat.status = ContratGestionStatus.ATTENTE_MGV.value
    contrat.sent_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(contrat)
    return contrat


async def send_to_mandant(db: AsyncSession, contrat: ContratGestion) -> ContratGestion:
    """Étape 2 : relais au Mandant après la signature MGV."""
    if not (contrat.mandant_courriel or "").strip():
        raise ContratGestionSendError("Courriel du Mandant manquant.")
    if not contrat.signature_token:
        contrat.signature_token = secrets.token_urlsafe(32)
        await db.flush()

    mailer = _mailer_or_raise()
    pdf_bytes = await _render_pdf(db, contrat)
    attachment = EmailAttachment(
        name=contrat_pdf_filename(contrat),
        content_bytes=pdf_bytes,
        content_type="application/pdf",
    )
    url = _sign_url(contrat.signature_token)
    try:
        await mailer.send(
            to=[contrat.mandant_courriel],
            subject=f"À signer — Convention de gestion — {MANDATAIRE_NOM}",
            html_body=_mandant_body(contrat, url),
            reply_to=mailer.sender,
            attachments=[attachment],
        )
    except Exception as exc:
        log.exception("Graph send (mandant) failed for contrat %s", contrat.id)
        raise ContratGestionSendError(f"Envoi courriel échoué: {exc}") from exc

    contrat.status = ContratGestionStatus.ATTENTE_CLIENT.value
    await db.flush()
    await db.refresh(contrat)
    return contrat


async def email_signed_to_both(
    db: AsyncSession, contrat: ContratGestion, signed_bytes: bytes
) -> None:
    """Étape 3 : envoie le PDF signé final aux deux parties (best-effort)."""
    del db
    recipients = [
        e
        for e in [contrat.mandataire_courriel, contrat.mandant_courriel]
        if (e or "").strip()
    ]
    if not recipients:
        return
    mailer = get_mailer()
    if not mailer.ready:
        log.warning("Mailer non prêt — PDF signé non envoyé (contrat %s)", contrat.id)
        return
    attachment = EmailAttachment(
        name=contrat_pdf_filename(contrat, signed=True),
        content_bytes=signed_bytes,
        content_type="application/pdf",
    )
    try:
        await mailer.send(
            to=recipients,
            subject=f"Convention de gestion signée — {MANDATAIRE_NOM}",
            html_body=_final_body(contrat),
            reply_to=mailer.sender,
            attachments=[attachment],
        )
    except Exception:
        log.exception("Envoi du PDF signé final échoué (contrat %s)", contrat.id)
