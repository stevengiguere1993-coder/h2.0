"""Endpoints publics (no auth) pour la signature d'un NDA.

Flow investisseur :
    GET  /api/v1/public/ndas/{token}        -> JSON détails publics
    GET  /api/v1/public/ndas/{token}/pdf    -> PDF inline
    POST /api/v1/public/ndas/{token}/sign   -> body {signed_name}

Le token est opaque (32 octets URL-safe) et fait office
d'authentification + audit trail (IP + nom + heure capturés).

Pas de bouton « refuser » : si l'investisseur ne veut pas signer,
il ne fait rien. Cela simplifie l'UX et évite un état « refusé »
qui n'apporterait aucune valeur côté Horizon (un refus est de
facto le statut par défaut, « non signé »).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.models.nda import NDA, NDAStatus
from app.services.audit import log_action
from app.services.nda_pdf import (
    generate_signed_nda_pdf,
    nda_pdf_filename,
    render_nda_pdf,
)
from app.services.nda_template import (
    ENGAGEMENT_ITEMS,
    ISSUER_ENTITY_NAME,
    NDA_DURATION_YEARS,
    NDA_JURISDICTION,
    render_nda_markdown,
)


log = logging.getLogger(__name__)


_MONTHS_FR_CA = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def _date_fr_ca_long(d: Optional[datetime]) -> str:
    if d is None:
        return ""
    dd = d.date() if isinstance(d, datetime) else d
    return f"{dd.day} {_MONTHS_FR_CA[dd.month - 1]} {dd.year}"


router = APIRouter(prefix="/public/ndas", tags=["public-ndas"])


# --------------------------- Schemas ---------------------------


class PublicNDA(BaseModel):
    """Vue publique épurée pour la page de signature.

    ⚠️ Ne JAMAIS exposer l'adresse de la propriété ici. Le NDA est
    signé AVANT que MGV identifie l'Opportunité à l'investisseur —
    si la page publique montrait l'adresse, le NDA n'aurait plus
    rien à protéger.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    investor_name: str
    issuer_name: str
    duration_years: int
    jurisdiction: str
    engagement_items: list[str]
    signed_name: Optional[str]
    signed_at: Optional[datetime]
    sent_at: Optional[datetime]
    # Texte intégral de l'entente, en Markdown, déjà rendu avec les
    # variables substituées. Affiché côté frontend dans un conteneur
    # scrollable — le destinataire doit avoir scrollé jusqu'en bas
    # avant que le bouton de signature s'active (cf. PR #517 fix).
    full_text_markdown: str
    # Date d'effet formatée pour le bandeau frontend (« 27 mai 2026 »).
    emission_date_formatted: str


_PHONE_ALLOWED_CHARS_RE = re.compile(r"^[0-9\s\-\(\)\.\+]+$")


class SignRequest(BaseModel):
    signed_name: str = Field(..., min_length=2, max_length=255)
    # Téléphone du Récepteur — requis depuis la PR « 4 fixes » pour
    # compléter le bloc Récepteur du NDA (Nom + Email + Téléphone +
    # Date + Signature). Format flexible : 10 à 15 chiffres, autorisant
    # espaces / tirets / parenthèses / points / `+`.
    phone: str = Field(..., min_length=10, max_length=32)
    # Flags d'attestation côté investisseur. Non bloquants côté
    # backend (l'UI gère le gating), mais loggés pour audit.
    has_scrolled: bool = False
    checkbox_confirmed: bool = False

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        v = (v or "").strip()
        if not _PHONE_ALLOWED_CHARS_RE.match(v):
            raise ValueError(
                "Numéro de téléphone invalide (chiffres / espaces / "
                "tirets / parenthèses / points / + seulement)."
            )
        digits = re.sub(r"\D", "", v)
        if len(digits) < 10 or len(digits) > 15:
            raise ValueError(
                "Numéro de téléphone invalide (10 à 15 chiffres requis)."
            )
        return v[:32]


# --------------------------- Helpers ---------------------------


def _client_ip(request: Request) -> Optional[str]:
    raw = (
        request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else None)
    )
    if raw:
        return raw.split(",")[0].strip()[:64]
    return None


async def _load_by_token(db: AsyncSession, token: str) -> NDA:
    nda = (
        await db.execute(
            select(NDA).where(NDA.signature_token == token)
        )
    ).scalar_one_or_none()
    if nda is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Lien invalide ou expiré."
        )
    return nda


async def _to_public(db: AsyncSession, nda: NDA) -> PublicNDA:
    # NOTE: on n'a plus besoin de charger le deal pour le rendu — le
    # NDA est désormais générique (pas d'adresse, pas de propriété).
    del db  # silence linter, conservé pour signature stable
    emission_date_obj = nda.sent_at or nda.signed_at
    emission_date_fmt = _date_fr_ca_long(emission_date_obj) or _date_fr_ca_long(
        datetime.now(timezone.utc)
    )
    signed_at_fmt = _date_fr_ca_long(nda.signed_at) if nda.signed_at else None
    full_md = render_nda_markdown(
        investor_name=nda.investor_name,
        emission_date=emission_date_fmt,
        signed_name=nda.signed_name,
        signed_at=signed_at_fmt,
    )
    return PublicNDA(
        id=nda.id,
        status=nda.status,
        investor_name=nda.investor_name,
        issuer_name=ISSUER_ENTITY_NAME,
        duration_years=NDA_DURATION_YEARS,
        jurisdiction=NDA_JURISDICTION,
        engagement_items=list(ENGAGEMENT_ITEMS),
        signed_name=nda.signed_name,
        signed_at=nda.signed_at,
        sent_at=nda.sent_at,
        full_text_markdown=full_md,
        emission_date_formatted=emission_date_fmt,
    )


# --------------------------- Routes ---------------------------


@router.get(
    "/{token}",
    response_model=PublicNDA,
    summary="Détails de l'entente (page publique)",
)
async def read_nda(token: str, db: DBSession) -> PublicNDA:
    nda = await _load_by_token(db, token)
    return await _to_public(db, nda)


@router.get(
    "/{token}/pdf",
    summary="PDF inline (page publique)",
)
async def public_nda_pdf(token: str, db: DBSession) -> Response:
    nda = await _load_by_token(db, token)
    pdf_bytes = await render_nda_pdf(db, nda.id)
    filename = nda_pdf_filename(nda)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post(
    "/{token}/sign",
    response_model=PublicNDA,
    summary="Signer l'entente",
)
async def sign_nda(
    token: str,
    data: SignRequest,
    request: Request,
    db: DBSession,
) -> PublicNDA:
    nda = await _load_by_token(db, token)
    if nda.status == NDAStatus.SIGNE.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Entente déjà signée."
        )

    nda.signed_name = data.signed_name.strip()[:255]
    nda.signed_phone = data.phone.strip()[:32]
    nda.signed_at = datetime.now(timezone.utc)
    nda.signed_ip = _client_ip(request)
    nda.status = NDAStatus.SIGNE.value
    # IMPORTANT — commit DB de la signature AVANT toute génération PDF.
    # Sinon, un timeout reportlab fait remonter une 502 Render-proxy
    # (HTML brut côté frontend, cf. bug rapporté par Phil) ET la
    # signature elle-même n'est pas persistée.
    await db.flush()
    await db.commit()
    await db.refresh(nda)

    # Génère le PDF signé immuable et le stocke en DB. Best-effort :
    # si le rendu plante OU prend trop de temps, la signature reste
    # valide en DB et le frontend pourra récupérer/regénérer le PDF
    # à la consultation via GET /api/v1/ndas/{id}/signed-pdf (lazy
    # generation). Ne JAMAIS lever d'exception ici : la signature DB
    # est ce qui importe légalement, le rendu PDF est secondaire.
    try:
        signed_bytes = await generate_signed_nda_pdf(db, nda.id)
        nda.signed_pdf_blob = signed_bytes
        await db.flush()
        await db.commit()
        await db.refresh(nda)
        log.info(
            "[NDA_SIGN] PDF signé généré et stocké pour NDA %s "
            "(%d octets)",
            nda.id,
            len(signed_bytes),
        )
        try:
            await log_action(
                db,
                user=None,
                action="nda.signed_pdf_generated",
                entity_type="nda",
                entity_id=nda.id,
                details={
                    "size_bytes": len(signed_bytes),
                    "signed_name": nda.signed_name,
                    "signed_ip": nda.signed_ip,
                },
            )
        except Exception:
            pass
    except Exception as exc:
        log.warning(
            "[NDA_SIGN] Génération PDF signé échouée pour NDA %s — "
            "signature DB conservée, blob laissé NULL (lazy generation "
            "à la 1ère consultation). Erreur: %s",
            nda.id,
            exc,
        )

    # Audit best-effort des attestations UX. Pas de table dédiée :
    # on logge dans les events serveur. Si Phil ajoute plus tard un
    # audit_log structuré pour les NDAs, ces deux flags y trouveront
    # naturellement leur place.
    log.info(
        "NDA %s signé par %s (IP=%s, scrolled=%s, checkbox=%s)",
        nda.id,
        nda.signed_name,
        nda.signed_ip,
        data.has_scrolled,
        data.checkbox_confirmed,
    )

    # Notification interne best-effort (ne fait pas échouer la
    # signature si la dépendance n'est pas dispo).
    try:
        from app.services.notifications import notify_role

        await notify_role(
            db,
            min_role="manager",
            kind="nda.signed",
            title=f"NDA #{nda.id} signé",
            body=f"Signé par {nda.signed_name}.",
            href=f"/prospection/pipeline/{nda.deal_id}",
        )
    except Exception:
        pass

    return await _to_public(db, nda)
