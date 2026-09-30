"""Signature PUBLIQUE d'un avenant de devis par le client (lien tokenisé,
sans compte) — retour Phil 2026-09-30.

    GET  /public/avenants/{token}          détail (changements, montants)
    GET  /public/avenants/{token}/pdf      PDF de l'avenant (signé si signé)
    POST /public/avenants/{token}/sign     signature tracée + nom → PDF
                                           signé archivé, copies courriel
    POST /public/avenants/{token}/decline  refus motivé
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.api.deps import DBSession
from app.models.client import Client
from app.models.contact_request import ContactRequest
from app.models.soumission import Soumission
from app.models.soumission_avenant import SoumissionAvenant
from app.services.avenant_pdf import (
    avenant_pdf_filename,
    montants_avenant,
    render_avenant_pdf,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/public/avenants", tags=["public-avenants"])

OP_LABELS = {"ajout": "Ajout", "retrait": "Retrait", "modification": "Modification"}


class PublicChange(BaseModel):
    op: str
    label: str
    description: str
    avant: Optional[dict] = None
    apres: Optional[dict] = None


class PublicAvenant(BaseModel):
    reference: str
    soumission_reference: str
    title: str
    note: Optional[str] = None
    status: str  # interne | envoye | signe | refuse
    signed_name: Optional[str] = None
    signed_at: Optional[datetime] = None
    changes: list[PublicChange]
    contrat_avant: float
    impact: float
    contrat_apres: float
    tps: float
    tvq: float
    total_apres: float
    company_name: str = "Horizon Services Immobiliers"
    company_rbq: str = "RBQ 5868-5991-01"
    company_email: str = "info@immohorizon.com"


class SignRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    signature_image_data_url: Optional[str] = Field(default=None, max_length=2_000_000)


class DeclineRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


def _decode_data_url(data_url: Optional[str]) -> tuple[Optional[bytes], Optional[str]]:
    import base64

    if not data_url or not data_url.startswith("data:"):
        return None, None
    try:
        header, b64 = data_url.split(",", 1)
        content_type = "image/png"
        after = header.split(":", 1)[1] if ":" in header else ""
        if ";" in after:
            content_type = after.split(";", 1)[0] or "image/png"
        raw = base64.b64decode(b64)
        return (raw if raw else None), content_type
    except Exception:  # noqa: BLE001
        return None, None


async def _load_by_token(db: AsyncSession, token: str) -> SoumissionAvenant:
    av = (
        await db.execute(
            select(SoumissionAvenant)
            .where(SoumissionAvenant.signature_token == token)
            .options(undefer(SoumissionAvenant.signature_image))
        )
    ).scalar_one_or_none()
    if av is None or av.signature_status == "interne":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lien invalide ou expiré.")
    return av


async def _detail(db: AsyncSession, av: SoumissionAvenant) -> PublicAvenant:
    sm = (await db.execute(select(Soumission).where(Soumission.id == av.soumission_id))).scalar_one()
    try:
        raw = json.loads(av.changes_json or "[]")
    except (TypeError, ValueError):
        raw = []
    changes = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        op = str(c.get("op") or "")
        avant, apres = c.get("avant"), c.get("apres")
        desc = (apres or avant or {}).get("description") or ""
        changes.append(PublicChange(op=op, label=OP_LABELS.get(op, op), description=desc, avant=avant, apres=apres))
    m = await montants_avenant(db, av)
    return PublicAvenant(
        reference=av.reference, soumission_reference=sm.reference, title=sm.title, note=av.note,
        status=av.signature_status, signed_name=av.signed_name, signed_at=av.signed_at,
        changes=changes, **m,
    )


@router.get("/{token}", response_model=PublicAvenant, summary="Avenant à signer (lien public)")
async def public_read(token: str, db: DBSession) -> PublicAvenant:
    av = await _load_by_token(db, token)
    try:
        if av.client_opened_at is None:
            av.client_opened_at = datetime.now(timezone.utc)
            await db.flush()
    except Exception:  # noqa: BLE001
        pass
    return await _detail(db, av)


@router.get("/{token}/pdf", summary="PDF de l'avenant (signé si signé)")
async def public_pdf(token: str, db: DBSession) -> Response:
    av = await _load_by_token(db, token)
    if av.signature_status == "signe":
        blob = (
            await db.execute(
                select(SoumissionAvenant.signed_pdf_blob).where(SoumissionAvenant.id == av.id)
            )
        ).scalar_one_or_none()
        if blob:
            sm = (await db.execute(select(Soumission).where(Soumission.id == av.soumission_id))).scalar_one()
            return Response(
                content=bytes(blob), media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="{avenant_pdf_filename(av, sm, signe=True)}"'},
            )
    rendered = await render_avenant_pdf(db, av.id)
    if rendered is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Avenant introuvable.")
    av, sm, pdf = rendered
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{avenant_pdf_filename(av, sm)}"'},
    )


async def _client_email(db: AsyncSession, sm: Soumission) -> Optional[str]:
    if sm.client_id:
        cl = await db.get(Client, sm.client_id)
        if cl is not None and cl.email:
            return cl.email
    if sm.contact_request_id:
        cr = (await db.execute(select(ContactRequest).where(ContactRequest.id == sm.contact_request_id))).scalar_one_or_none()
        if cr is not None and cr.email:
            return cr.email
    return None


@router.post("/{token}/sign", response_model=PublicAvenant, summary="Le client signe l'avenant")
async def public_sign(token: str, data: SignRequest, request: Request, db: DBSession) -> PublicAvenant:
    av = await _load_by_token(db, token)
    if av.signature_status == "signe":
        raise HTTPException(status.HTTP_409_CONFLICT, "Cet avenant est déjà signé.")
    sig_bytes, sig_ct = _decode_data_url(data.signature_image_data_url)
    if not sig_bytes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La signature tracée est obligatoire.")
    raw_ip = request.headers.get("x-forwarded-for") or (request.client.host if request.client else None)
    if raw_ip:
        raw_ip = raw_ip.split(",")[0].strip()[:64]
    now = datetime.now(timezone.utc)
    av.signature_status = "signe"
    av.signed_at = now
    av.signed_name = data.name.strip()[:255]
    av.signed_ip = raw_ip
    av.declined_at = None
    av.decline_reason = None
    await db.flush()
    # Image de signature + PDF signé : écrits par UPDATE isolé (SAVEPOINT)
    # pour que l'archivage n'avorte jamais la signature elle-même.
    try:
        async with db.begin_nested():
            await db.execute(
                update(SoumissionAvenant).where(SoumissionAvenant.id == av.id)
                .values(signature_image=sig_bytes, signature_image_content_type=sig_ct)
            )
    except Exception:  # noqa: BLE001
        log.warning("Signature image non stockée pour avenant %s", av.id, exc_info=True)
    await db.commit()

    pdf_bytes: Optional[bytes] = None
    sm: Optional[Soumission] = None
    try:
        rendered = await render_avenant_pdf(db, av.id)
        if rendered is not None:
            av, sm, pdf_bytes = rendered
            async with db.begin_nested():
                await db.execute(
                    update(SoumissionAvenant).where(SoumissionAvenant.id == av.id).values(signed_pdf_blob=pdf_bytes)
                )
            await db.commit()
    except Exception:  # noqa: BLE001
        log.exception("PDF signé de l'avenant %s non généré", av.id)

    # Copies : au client (PDF signé) et aux gestionnaires (cloche + push).
    try:
        if sm is None:
            sm = (await db.execute(select(Soumission).where(Soumission.id == av.soumission_id))).scalar_one()
        recipient = await _client_email(db, sm)
        if recipient and pdf_bytes:
            from app.integrations.email_graph import EmailAttachment, get_mailer

            mailer = get_mailer()
            if mailer.ready:
                await mailer.send(
                    to=[recipient],
                    subject=f"Votre avenant signé — {av.reference} (soumission {sm.reference})",
                    html_body=(
                        "<p>Bonjour,</p>"
                        f"<p>Merci d'avoir signé l'avenant <b>{av.reference}</b> à votre soumission "
                        f"<b>{sm.reference}</b>. Vous trouverez en pièce jointe le PDF avec votre signature.</p>"
                        "<p>L'équipe Horizon Services Immobiliers</p>"
                    ),
                    reply_to=mailer.sender,
                    attachments=[EmailAttachment(
                        name=avenant_pdf_filename(av, sm, signe=True), content_bytes=pdf_bytes,
                        content_type="application/pdf",
                    )],
                )
    except Exception:  # noqa: BLE001
        log.warning("Envoi du PDF signé de l'avenant %s échoué", av.id, exc_info=True)
    try:
        from app.services.notifications import notify_role

        await notify_role(
            db, min_role="manager", kind="avenant.signed",
            title=f"Avenant {av.reference} signé — soumission {sm.reference if sm else av.soumission_id}",
            body=f"Signé par {av.signed_name} en ligne.",
            href=f"/app/soumissions/{av.soumission_id}",
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        log.warning("Notification avenant signé échouée pour %s", av.id, exc_info=True)
    return await _detail(db, av)


@router.post("/{token}/decline", response_model=PublicAvenant, summary="Le client refuse l'avenant")
async def public_decline(token: str, data: DeclineRequest, db: DBSession) -> PublicAvenant:
    av = await _load_by_token(db, token)
    if av.signature_status == "signe":
        raise HTTPException(status.HTTP_409_CONFLICT, "Cet avenant est déjà signé.")
    av.signature_status = "refuse"
    av.declined_at = datetime.now(timezone.utc)
    av.decline_reason = (data.reason or "").strip()[:500] or None
    await db.flush()
    try:
        from app.services.notifications import notify_role

        await notify_role(
            db, min_role="manager", kind="avenant.declined",
            title=f"Avenant {av.reference} refusé par le client",
            body=av.decline_reason or "Sans motif.",
            href=f"/app/soumissions/{av.soumission_id}",
        )
    except Exception:  # noqa: BLE001
        log.warning("Notification avenant refusé échouée pour %s", av.id, exc_info=True)
    return await _detail(db, av)
