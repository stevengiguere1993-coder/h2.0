"""Endpoints publics (no auth) — signature d'un contrat de gestion.

    GET  /api/v1/public/contrats-gestion/{token}        JSON + suivi ouverture
    GET  /api/v1/public/contrats-gestion/{token}/pdf    PDF inline
    POST /api/v1/public/contrats-gestion/{token}/sign   body {signed_name, ...}

Le Mandant signe une seule fois : la même signature remplit le bloc
Mandant et (si requise) le bloc Caution solidaire — cf. décision Phil.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
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
from app.services.contrat_gestion_service import (
    get_template_markdown,
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
    mandataire_name: str
    compagnie: Optional[str]
    representant_nom: Optional[str]
    caution_requise: bool
    signed_name: Optional[str]
    signed_at: Optional[datetime]
    sent_at: Optional[datetime]
    body_markdown: str


class SignRequest(BaseModel):
    signed_name: str = Field(..., min_length=2, max_length=255)
    # Signature manuscrite (data-URL PNG). Facultative : la saisie du
    # nom + l'attestation suffisent à la validité (art. 2827 C.c.Q.).
    signature_image_data_url: Optional[str] = Field(default=None, max_length=2_000_000)
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


def _decode_data_url(data_url: Optional[str]) -> tuple[Optional[bytes], Optional[str]]:
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


async def _load_by_token(db: AsyncSession, token: str) -> ContratGestion:
    contrat = (
        await db.execute(
            select(ContratGestion).where(ContratGestion.signature_token == token)
        )
    ).scalar_one_or_none()
    if contrat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lien invalide ou expiré.")
    return contrat


async def _to_public(db: AsyncSession, contrat: ContratGestion) -> PublicContrat:
    body = await resolve_body_markdown(db, contrat)
    return PublicContrat(
        id=contrat.id,
        status=contrat.status,
        mandataire_name=MANDATAIRE_NOM,
        compagnie=contrat.compagnie,
        representant_nom=contrat.representant_nom,
        caution_requise=contrat.caution_requise,
        signed_name=contrat.signed_name,
        signed_at=contrat.signed_at,
        sent_at=contrat.sent_at,
        body_markdown=body,
    )


@router.get("/{token}", response_model=PublicContrat, summary="Détail (page publique)")
async def read_contrat(token: str, db: DBSession) -> PublicContrat:
    contrat = await _load_by_token(db, token)
    # Accusé de lecture (best-effort) — ne bloque jamais l'affichage.
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
    return await _to_public(db, contrat)


@router.get("/{token}/pdf", summary="PDF inline (page publique)")
async def public_contrat_pdf(token: str, db: DBSession) -> Response:
    contrat = await _load_by_token(db, token)
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
    contrat = await _load_by_token(db, token)
    if contrat.status == ContratGestionStatus.SIGNE.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Convention déjà signée.")

    signed_name = data.signed_name.strip()[:255]
    contrat.signed_name = signed_name
    contrat.signed_at = datetime.now(timezone.utc)
    contrat.signed_ip = _client_ip(request)
    if not (contrat.caution_nom or "").strip():
        contrat.caution_nom = signed_name

    sig_bytes, sig_ct = _decode_data_url(data.signature_image_data_url)
    if sig_bytes:
        contrat.signature_image = sig_bytes
        contrat.signature_image_content_type = sig_ct

    # Fige le corps avec la date de signature (le contrat garde sa version).
    template_md = await get_template_markdown(db)
    contrat.corps_markdown = render_body(template_md, contrat)
    contrat.status = ContratGestionStatus.SIGNE.value

    # Commit DB de la signature AVANT génération PDF (sécurité timeout).
    await db.flush()
    await db.commit()

    # PDF signé immuable — best-effort.
    try:
        reloaded = (
            await db.execute(
                select(ContratGestion)
                .where(ContratGestion.id == contrat.id)
                .options(undefer(ContratGestion.signature_image))
            )
        ).scalar_one()
        signed_bytes = generate_signed_contrat_pdf(reloaded, reloaded.corps_markdown or "")
        reloaded.signed_pdf_blob = signed_bytes
        await db.flush()
        await db.commit()
        contrat = reloaded
        try:
            await log_action(
                db, user=None, action="contrat_gestion.signed",
                entity_type="contrat_gestion", entity_id=contrat.id,
                details={"signed_name": signed_name, "signed_ip": contrat.signed_ip},
            )
            await db.commit()
        except Exception:
            pass

        # Archivage Drive (best-effort, non bloquant).
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
            "[CG_SIGN] Génération PDF signé échouée (contrat %s) — signature "
            "conservée, blob NULL (lazy à la consultation). Erreur: %s",
            contrat.id, exc,
        )

    # Notification interne best-effort.
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

    return await _to_public(db, contrat)
