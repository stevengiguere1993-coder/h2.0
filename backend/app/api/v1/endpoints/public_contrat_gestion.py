"""Endpoints publics (no auth) — signature d'un contrat de gestion.

Flux à deux signatures :
1. Le signataire MGV (Mandataire) ouvre son lien et signe.
2. La convention est relayée automatiquement au Mandant, qui signe.
3. Le PDF final signé des deux est envoyé par courriel aux deux parties.

Un même endpoint sert les deux signataires : le token identifie la
partie (`mandataire_signature_token` vs `signature_token`).
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.api.deps import DBSession
from app.models.contrat_gestion import ContratGestion, ContratGestionStatus
from app.services.audit import log_action
from app.services.contrat_gestion_pdf import (
    contrat_pdf_filename,
    generate_signed_contrat_pdf,
    render_contrat_pdf,
)
from app.services.contrat_gestion_send import (
    email_signed_to_both,
    send_to_mandant,
)
from app.services.contrat_gestion_service import (
    effective_template_markdown,
    render_body,
    resolve_body_markdown,
)
from app.services.contrat_gestion_template import MANDATAIRE_NOM

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/public/contrats-gestion", tags=["public-contrats-gestion"]
)


class PublicContrat(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    party: str  # "mandataire" | "mandant"
    mandataire_name: str
    compagnie: Optional[str]
    representant_nom: Optional[str]
    caution_requise: bool
    already_signed: bool
    signed_name: Optional[str]
    signed_at: Optional[datetime]
    body_markdown: str


class SignRequest(BaseModel):
    signed_name: str = Field(..., min_length=2, max_length=255)
    # Signature manuscrite obligatoire (data-URL PNG).
    signature_image_data_url: str = Field(..., min_length=20, max_length=2_000_000)
    has_scrolled: bool = False
    checkbox_confirmed: bool = False


def _client_ip(request: Request) -> Optional[str]:
    raw = (
        request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else None)
    )
    if raw:
        return raw.split(",")[0].strip()[:64]
    return None


def _decode_data_url(data_url: str) -> tuple[Optional[bytes], Optional[str]]:
    if not data_url or not data_url.startswith("data:"):
        return None, None
    try:
        header, b64 = data_url.split(",", 1)
        ct = "image/png"
        if ":" in header:
            after = header.split(":", 1)[1]
            ct = after.split(";", 1)[0] if ";" in after else after
        raw = base64.b64decode(b64, validate=False)
        if len(raw) > 1_500_000:
            return None, None
        return raw, ct
    except Exception:
        return None, None


async def _load_by_token(
    db: AsyncSession, token: str
) -> tuple[ContratGestion, str]:
    """Renvoie (contrat, party) — party = 'mandataire' ou 'mandant'."""
    contrat = (
        await db.execute(
            select(ContratGestion).where(
                or_(
                    ContratGestion.signature_token == token,
                    ContratGestion.mandataire_signature_token == token,
                )
            )
        )
    ).scalar_one_or_none()
    if contrat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lien invalide ou expiré.")
    party = (
        "mandataire"
        if contrat.mandataire_signature_token == token
        else "mandant"
    )
    return contrat, party


async def _to_public(
    db: AsyncSession, contrat: ContratGestion, party: str
) -> PublicContrat:
    body = await resolve_body_markdown(db, contrat)
    if party == "mandataire":
        already = contrat.mandataire_signed_at is not None
        who = contrat.mandataire_signed_name
        when = contrat.mandataire_signed_at
    else:
        already = contrat.signed_at is not None
        who = contrat.signed_name
        when = contrat.signed_at
    return PublicContrat(
        id=contrat.id,
        status=contrat.status,
        party=party,
        mandataire_name=MANDATAIRE_NOM,
        compagnie=contrat.compagnie,
        representant_nom=contrat.representant_nom,
        caution_requise=contrat.caution_requise,
        already_signed=already,
        signed_name=who,
        signed_at=when,
        body_markdown=body,
    )


@router.get("/{token}", response_model=PublicContrat, summary="Détail (page publique)")
async def read_contrat(token: str, db: DBSession) -> PublicContrat:
    contrat, party = await _load_by_token(db, token)
    if contrat.status != ContratGestionStatus.SIGNE.value:
        try:
            now = datetime.now(timezone.utc)
            if contrat.opened_at is None:
                contrat.opened_at = now
            contrat.last_opened_at = now
            contrat.open_count = (contrat.open_count or 0) + 1
            await db.commit()
        except Exception:
            await db.rollback()
    return await _to_public(db, contrat, party)


@router.get("/{token}/pdf", summary="PDF inline (page publique)")
async def public_contrat_pdf(token: str, db: DBSession) -> Response:
    contrat, _party = await _load_by_token(db, token)
    body = await resolve_body_markdown(db, contrat)
    pdf_bytes = render_contrat_pdf(contrat, body)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="{contrat_pdf_filename(contrat)}"'
            )
        },
    )


@router.post("/{token}/sign", response_model=PublicContrat, summary="Signer")
async def sign_contrat(
    token: str, data: SignRequest, request: Request, db: DBSession
) -> PublicContrat:
    contrat, party = await _load_by_token(db, token)

    sig_bytes, sig_ct = _decode_data_url(data.signature_image_data_url)
    if not sig_bytes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Signature manuscrite requise.",
        )
    signed_name = data.signed_name.strip()[:255]
    ip = _client_ip(request)

    if party == "mandataire":
        return await _sign_mandataire(db, contrat, signed_name, ip, sig_bytes, sig_ct)
    return await _sign_mandant(db, contrat, signed_name, ip, sig_bytes, sig_ct)


async def _sign_mandataire(
    db: AsyncSession,
    contrat: ContratGestion,
    signed_name: str,
    ip: Optional[str],
    sig_bytes: bytes,
    sig_ct: Optional[str],
) -> PublicContrat:
    if contrat.mandataire_signed_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Déjà signé par le Mandataire."
        )
    contrat.mandataire_signed_name = signed_name
    contrat.mandataire_signed_at = datetime.now(timezone.utc)
    contrat.mandataire_signed_ip = ip
    contrat.mandataire_signature_image = sig_bytes
    contrat.mandataire_signature_image_content_type = sig_ct
    contrat.status = ContratGestionStatus.ATTENTE_CLIENT.value
    await db.flush()
    await db.commit()

    # Relais au Mandant (best-effort — le token Mandant est créé même si
    # l'envoi échoue, pour permettre de copier le lien depuis l'onglet).
    try:
        reloaded = (
            await db.execute(
                select(ContratGestion)
                .where(ContratGestion.id == contrat.id)
                .options(undefer(ContratGestion.mandataire_signature_image))
            )
        ).scalar_one()
        await send_to_mandant(db, reloaded)
        await db.commit()
        contrat = reloaded
    except Exception:
        log.exception("Relais au Mandant échoué (contrat %s)", contrat.id)
    try:
        await log_action(
            db, user=None, action="contrat_gestion.mandataire_signed",
            entity_type="contrat_gestion", entity_id=contrat.id,
            details={"signed_name": signed_name, "signed_ip": ip},
        )
        await db.commit()
    except Exception:
        pass
    return await _to_public(db, contrat, "mandataire")


async def _sign_mandant(
    db: AsyncSession,
    contrat: ContratGestion,
    signed_name: str,
    ip: Optional[str],
    sig_bytes: bytes,
    sig_ct: Optional[str],
) -> PublicContrat:
    if contrat.signed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Convention déjà signée.")

    contrat.signed_name = signed_name
    contrat.signed_at = datetime.now(timezone.utc)
    contrat.signed_ip = ip
    contrat.signature_image = sig_bytes
    contrat.signature_image_content_type = sig_ct
    if not (contrat.caution_nom or "").strip():
        contrat.caution_nom = signed_name

    template_md = await effective_template_markdown(db, contrat)
    contrat.corps_markdown = render_body(template_md, contrat)
    contrat.status = ContratGestionStatus.SIGNE.value

    await db.flush()
    await db.commit()

    # PDF signé final (deux signatures) — best-effort.
    try:
        reloaded = (
            await db.execute(
                select(ContratGestion)
                .where(ContratGestion.id == contrat.id)
                .options(
                    undefer(ContratGestion.signature_image),
                    undefer(ContratGestion.mandataire_signature_image),
                )
            )
        ).scalar_one()
        signed_bytes = generate_signed_contrat_pdf(
            reloaded, reloaded.corps_markdown or ""
        )
        reloaded.signed_pdf_blob = signed_bytes
        await db.flush()
        await db.commit()
        contrat = reloaded
        try:
            await log_action(
                db, user=None, action="contrat_gestion.signed",
                entity_type="contrat_gestion", entity_id=contrat.id,
                details={"signed_name": signed_name, "signed_ip": ip},
            )
            await db.commit()
        except Exception:
            pass

        # Envoi du PDF signé aux deux parties (best-effort).
        try:
            await email_signed_to_both(db, contrat, signed_bytes)
        except Exception:
            log.exception("Envoi PDF signé aux deux échoué (contrat %s)", contrat.id)

        # Archivage Drive (best-effort).
        try:
            from app.services.drive_auto_upload_dispatcher import (
                dispatch_auto_upload,
            )

            await dispatch_auto_upload(
                "contrat_gestion_signed",
                "Immeuble",
                contrat.immeuble_id,
                None,
                signed_bytes,
                db,
                {"nom_signataire": signed_name, "compagnie": contrat.compagnie or ""},
                mime_type="application/pdf",
            )
            await db.commit()
        except Exception:
            log.exception("Auto-upload Drive contrat de gestion signé non bloquant")
    except Exception as exc:
        log.warning(
            "[CG_SIGN] Génération PDF signé échouée (contrat %s): %s",
            contrat.id, exc,
        )

    try:
        from app.services.notifications import notify_role

        await notify_role(
            db,
            min_role="manager",
            kind="contrat_gestion.signed",
            title=f"Contrat de gestion #{contrat.id} signé",
            body=f"Signé par {signed_name}.",
            href=f"/immobilier/immeubles/{contrat.immeuble_id}",
        )
    except Exception:
        pass

    return await _to_public(db, contrat, "mandant")
