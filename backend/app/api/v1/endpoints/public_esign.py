"""eSign — endpoints PUBLICS (no auth) pour la page de signature.

Flow signataire :
    GET  /public/esign/{token}              -> détails + suivi d'ouverture
    GET  /public/esign/{token}/pages/{n}    -> page rendue en PNG
    GET  /public/esign/{token}/pdf          -> PDF original inline
    GET  /public/esign/{token}/signed-pdf   -> PDF final (une fois complété)
    POST /public/esign/{token}/sms/send     -> envoie le code de validation SMS
    POST /public/esign/{token}/sms/verify   -> vérifie le code
    POST /public/esign/{token}/sign         -> signe (images + textes + consentement)
    POST /public/esign/{token}/decline      -> refuse (avec raison)

Le token (32 octets URL-safe, unique par signataire) fait office
d'authentification. Si le signataire exige l'authentification SMS,
un code à 6 chiffres (haché SHA-256 en DB, expirant après 10 min)
doit être vérifié avant que POST /sign ne soit accepté.

⚠️ Comme pour les autres modules : la signature est COMMITÉE en DB
AVANT toute génération de PDF (un timeout reportlab ne doit jamais
perdre une signature).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.api.deps import DBSession
from app.core.config import settings
from app.models.entreprise import Entreprise
from app.models.esign import (
    EsignAttachment,
    EsignDocument,
    EsignDocumentStatus,
    EsignEvent,
    EsignField,
    EsignFieldKind,
    EsignObserver,
    EsignSigner,
)
from app.services.esign_pdf import (
    build_final_pdf,
    date_fr_ca_long,
    final_pdf_filename,
    page_png,
)
from app.services.esign_send import (
    EsignSendError,
    send_completion_emails,
    send_signer_invitation,
    signers_to_invite,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/public/esign", tags=["public-esign"])

_SMS_CODE_TTL_MINUTES = 10
_SMS_MAX_SENDS = 8
_SMS_MIN_INTERVAL_SECONDS = 60
_SMS_MAX_ATTEMPTS = 6
_IMG_MAX_BYTES = 2 * 1024 * 1024
_DATA_URL_RE = re.compile(r"^data:image/png;base64,(?P<b64>[A-Za-z0-9+/=\s]+)$")


# --------------------------- Schemas ---------------------------


class PublicField(BaseModel):
    id: int
    signer_id: int
    mine: bool
    signer_name: str
    signer_signed: bool
    kind: str
    page: int
    x: float
    y: float
    w: float
    h: float
    required: bool
    label: Optional[str]
    value_text: Optional[str]


class PublicSignerSummary(BaseModel):
    name: str
    is_me: bool
    signed_at: Optional[datetime]
    declined: bool


class PublicAttachment(BaseModel):
    id: int
    filename: str
    size_bytes: int


class PublicEsign(BaseModel):
    title: str
    status: str
    page_count: int
    entreprise_name: Optional[str]
    message: Optional[str]
    expires_at: Optional[datetime]
    attachments: List[PublicAttachment]
    signer_first_name: str
    signer_last_name: str
    signer_email: str
    already_signed: bool
    already_declined: bool
    is_my_turn: bool
    sms_required: bool
    sms_verified: bool
    phone_masked: Optional[str]
    fields: List[PublicField]
    signers: List[PublicSignerSummary]
    completed: bool


class SmsSendResult(BaseModel):
    sent: bool
    phone_masked: Optional[str]


class SmsVerifyRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=8)


class TextValue(BaseModel):
    field_id: int
    value: str = Field(default="", max_length=500)


class SignRequest(BaseModel):
    signature_data_url: Optional[str] = None
    initials_data_url: Optional[str] = None
    text_values: List[TextValue] = Field(default_factory=list)
    consent: bool = False


class DeclineRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


# --------------------------- Helpers ---------------------------


def _client_ip(request: Request) -> Optional[str]:
    raw = (
        request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else None)
    )
    if raw:
        return raw.split(",")[0].strip()[:64]
    return None


def _mask_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 4:
        return "•••"
    return f"••• ••• {digits[-4:]}"


def _normalize_e164(phone: str) -> str:
    p = (phone or "").strip()
    if p.startswith("+"):
        return "+" + re.sub(r"\D", "", p[1:])
    digits = re.sub(r"\D", "", p)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}" if digits else ""


def _decode_png_data_url(data_url: str, what: str) -> bytes:
    m = _DATA_URL_RE.match((data_url or "").strip())
    if not m:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Image {what} invalide (PNG data-URL attendu).",
        )
    try:
        raw = base64.b64decode(m.group("b64"), validate=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Image {what} illisible.",
        ) from exc
    if not raw or len(raw) > _IMG_MAX_BYTES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Image {what} vide ou trop volumineuse (max 2 Mo).",
        )
    return raw


async def _load_by_token(
    db: AsyncSession, token: str
) -> tuple[EsignSigner, EsignDocument]:
    signer = (
        await db.execute(
            select(EsignSigner).where(EsignSigner.signature_token == token)
        )
    ).scalar_one_or_none()
    if signer is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Lien invalide ou expiré."
        )
    doc = (
        await db.execute(
            select(EsignDocument).where(
                EsignDocument.id == signer.document_id
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Lien invalide ou expiré."
        )
    if doc.status == EsignDocumentStatus.ANNULE.value:
        raise HTTPException(
            status.HTTP_410_GONE, "Ce document a été annulé par l'émetteur."
        )
    if doc.status == EsignDocumentStatus.EXPIRE.value:
        raise HTTPException(
            status.HTTP_410_GONE,
            "Ce lien de signature a expiré — contactez l'émetteur du "
            "document.",
        )
    # Expiration « live » : la date peut être dépassée avant le passage
    # du cron quotidien qui bascule le statut.
    if (
        doc.status == EsignDocumentStatus.ENVOYE.value
        and doc.expires_at is not None
    ):
        exp = doc.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= datetime.now(timezone.utc):
            raise HTTPException(
                status.HTTP_410_GONE,
                "Ce lien de signature a expiré — contactez l'émetteur du "
                "document.",
            )
    return signer, doc


async def _doc_signers(db: AsyncSession, doc_id: int) -> list[EsignSigner]:
    return list(
        (
            await db.execute(
                select(EsignSigner)
                .where(EsignSigner.document_id == doc_id)
                .order_by(EsignSigner.order_index, EsignSigner.id)
            )
        ).scalars()
    )


def _is_my_turn(
    doc: EsignDocument, signers: list[EsignSigner], me: EsignSigner
) -> bool:
    if not doc.use_signing_order:
        return True
    pending = [s for s in signers if not s.signed_at and not s.declined_at]
    if not pending:
        return False
    return me.order_index == min(s.order_index for s in pending)


async def _add_event(
    db: AsyncSession,
    doc: EsignDocument,
    type_: str,
    signer: Optional[EsignSigner] = None,
    ip: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    db.add(
        EsignEvent(
            document_id=doc.id,
            signer_id=signer.id if signer else None,
            type=type_,
            ip=ip,
            detail=(detail or None),
        )
    )
    await db.flush()


async def _to_public(
    db: AsyncSession, signer: EsignSigner, doc: EsignDocument
) -> PublicEsign:
    signers = await _doc_signers(db, doc.id)
    fields = list(
        (
            await db.execute(
                select(EsignField)
                .where(EsignField.document_id == doc.id)
                .order_by(EsignField.page, EsignField.id)
            )
        ).scalars()
    )
    by_id = {s.id: s for s in signers}
    ent_name = None
    if doc.entreprise_id:
        ent_name = (
            await db.execute(
                select(Entreprise.name).where(
                    Entreprise.id == doc.entreprise_id
                )
            )
        ).scalar_one_or_none()

    def _name(s: EsignSigner) -> str:
        return f"{s.first_name} {s.last_name}".strip()

    attachments = list(
        (
            await db.execute(
                select(EsignAttachment)
                .where(EsignAttachment.document_id == doc.id)
                .order_by(EsignAttachment.id)
            )
        ).scalars()
    )
    return PublicEsign(
        title=doc.title,
        status=doc.status,
        page_count=doc.page_count,
        entreprise_name=ent_name,
        message=doc.message,
        expires_at=doc.expires_at,
        attachments=[
            PublicAttachment(
                id=a.id, filename=a.filename, size_bytes=a.size_bytes
            )
            for a in attachments
        ],
        signer_first_name=signer.first_name,
        signer_last_name=signer.last_name,
        signer_email=signer.email,
        already_signed=signer.signed_at is not None,
        already_declined=signer.declined_at is not None,
        is_my_turn=_is_my_turn(doc, signers, signer),
        sms_required=signer.require_sms_auth,
        sms_verified=signer.sms_verified_at is not None,
        phone_masked=_mask_phone(signer.phone),
        fields=[
            PublicField(
                id=f.id,
                signer_id=f.signer_id,
                mine=f.signer_id == signer.id,
                signer_name=_name(by_id[f.signer_id])
                if f.signer_id in by_id
                else "—",
                signer_signed=(
                    by_id[f.signer_id].signed_at is not None
                    if f.signer_id in by_id
                    else False
                ),
                kind=f.kind,
                page=f.page,
                x=f.x,
                y=f.y,
                w=f.w,
                h=f.h,
                required=f.required,
                label=f.label,
                value_text=f.value_text,
            )
            for f in fields
        ],
        signers=[
            PublicSignerSummary(
                name=_name(s),
                is_me=s.id == signer.id,
                signed_at=s.signed_at,
                declined=s.declined_at is not None,
            )
            for s in signers
        ],
        completed=doc.status == EsignDocumentStatus.COMPLETE.value,
    )


# --------------------------- Routes ---------------------------


@router.get(
    "/{token}",
    response_model=PublicEsign,
    summary="Détails du document pour le signataire (suivi d'ouverture)",
)
async def read_esign(
    token: str, request: Request, db: DBSession
) -> PublicEsign:
    signer, doc = await _load_by_token(db, token)
    # Suivi d'ouverture — seulement tant que le signataire n'a pas signé
    # (les re-consultations post-signature ne polluent pas le journal).
    now = datetime.now(timezone.utc)
    signer.open_count = (signer.open_count or 0) + 1
    signer.last_opened_at = now
    first_open = signer.opened_at is None
    if first_open:
        signer.opened_at = now
    await db.flush()
    if first_open or not signer.signed_at:
        # Une entrée par ouverture avant signature ; la toute première
        # est marquée comme telle.
        await _add_event(
            db,
            doc,
            "ouvert",
            signer=signer,
            ip=_client_ip(request),
            detail="première ouverture" if first_open else None,
        )
    await db.commit()
    return await _to_public(db, signer, doc)


@router.get(
    "/{token}/pages/{page_number}",
    summary="Page du PDF rendue en PNG",
)
async def esign_page_png(
    token: str, page_number: int, db: DBSession
) -> Response:
    signer, doc = await _load_by_token(db, token)
    doc_blob = (
        await db.execute(
            select(EsignDocument)
            .where(EsignDocument.id == doc.id)
            .options(undefer(EsignDocument.pdf_blob))
        )
    ).scalar_one()
    if page_number < 1 or page_number > max(doc.page_count, 1):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page hors limites.")
    try:
        png = await asyncio.to_thread(
            page_png, bytes(doc_blob.pdf_blob), page_number, 130
        )
    except Exception as exc:  # noqa: BLE001
        log.exception(
            "eSign public : rendu page %s (doc %s) échoué",
            page_number, doc.id,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Rendu de page échoué."
        ) from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/{token}/pdf", summary="PDF original inline")
async def esign_pdf(token: str, db: DBSession) -> Response:
    signer, doc = await _load_by_token(db, token)
    doc_blob = (
        await db.execute(
            select(EsignDocument)
            .where(EsignDocument.id == doc.id)
            .options(undefer(EsignDocument.pdf_blob))
        )
    ).scalar_one()
    return Response(
        content=bytes(doc_blob.pdf_blob),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{doc.filename}"'
        },
    )


@router.get(
    "/{token}/attachments/{attachment_id}",
    summary="Télécharge une annexe consultable",
)
async def esign_attachment(
    token: str, attachment_id: int, db: DBSession
) -> Response:
    signer, doc = await _load_by_token(db, token)
    att = (
        await db.execute(
            select(EsignAttachment)
            .where(
                EsignAttachment.id == attachment_id,
                EsignAttachment.document_id == doc.id,
            )
            .options(undefer(EsignAttachment.blob))
        )
    ).scalar_one_or_none()
    if att is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annexe introuvable.")
    return Response(
        content=bytes(att.blob),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{att.filename}"'
        },
    )


@router.get(
    "/{token}/signed-pdf",
    summary="PDF final aplati (disponible une fois le document complété)",
)
async def esign_signed_pdf(token: str, db: DBSession) -> Response:
    signer, doc = await _load_by_token(db, token)
    doc_blob = (
        await db.execute(
            select(EsignDocument)
            .where(EsignDocument.id == doc.id)
            .options(undefer(EsignDocument.signed_pdf_blob))
        )
    ).scalar_one()
    if not doc_blob.signed_pdf_blob:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "PDF final pas encore disponible.",
        )
    return Response(
        content=bytes(doc_blob.signed_pdf_blob),
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'inline; filename="{final_pdf_filename(doc)}"'
        },
    )


# --------------------------- SMS ---------------------------


@router.post(
    "/{token}/sms/send",
    response_model=SmsSendResult,
    summary="Envoie le code de validation par SMS",
)
async def send_sms_code(
    token: str, request: Request, db: DBSession
) -> SmsSendResult:
    signer, doc = await _load_by_token(db, token)
    if not signer.require_sms_auth:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Aucune authentification SMS requise pour ce signataire.",
        )
    if signer.signed_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Document déjà signé."
        )
    if not (signer.phone or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Aucun numéro de téléphone au dossier — contactez l'émetteur.",
        )
    now = datetime.now(timezone.utc)
    if (signer.sms_sent_count or 0) >= _SMS_MAX_SENDS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Trop de codes envoyés — contactez l'émetteur du document.",
        )
    if signer.sms_last_sent_at is not None:
        last = signer.sms_last_sent_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (now - last).total_seconds()
        if elapsed < _SMS_MIN_INTERVAL_SECONDS:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Patientez {int(_SMS_MIN_INTERVAL_SECONDS - elapsed)} s "
                "avant de redemander un code.",
            )

    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Envoi SMS non configuré — contactez l'émetteur du document.",
        )

    # Numéro expéditeur : premier numéro actif du volet Téléphonie,
    # sinon le numéro Twilio de la config.
    from_e164: Optional[str] = None
    try:
        from app.models.voice import PhoneNumber

        pn = (
            await db.execute(
                select(PhoneNumber)
                .where(PhoneNumber.active.is_(True))
                .order_by(PhoneNumber.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if pn is not None:
            from_e164 = pn.e164
    except Exception:  # noqa: BLE001
        pass
    from_e164 = from_e164 or settings.twilio_phone_number
    if not from_e164:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Aucun numéro expéditeur SMS configuré.",
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    body = (
        f"Votre code de vérification Horizon : {code} "
        f"(valide {_SMS_CODE_TTL_MINUTES} minutes). "
        f"Document : {doc.title[:60]}"
    )
    try:
        from app.integrations.voice.twilio_provider import (
            TwilioVoiceProvider,
        )

        provider = TwilioVoiceProvider(
            settings.twilio_account_sid, settings.twilio_auth_token
        )
        await provider.send_sms(
            from_e164=from_e164,
            to_e164=_normalize_e164(signer.phone),
            body=body,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception(
            "eSign : envoi SMS échoué (doc %s, signataire %s)",
            doc.id, signer.id,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Envoi du SMS échoué — réessayez dans quelques instants.",
        ) from exc

    signer.sms_code_hash = hashlib.sha256(code.encode()).hexdigest()
    signer.sms_code_expires_at = now + timedelta(
        minutes=_SMS_CODE_TTL_MINUTES
    )
    signer.sms_code_attempts = 0
    signer.sms_sent_count = (signer.sms_sent_count or 0) + 1
    signer.sms_last_sent_at = now
    await db.flush()
    await _add_event(
        db, doc, "sms_envoye", signer=signer, ip=_client_ip(request),
        detail=_mask_phone(signer.phone),
    )
    await db.commit()
    return SmsSendResult(sent=True, phone_masked=_mask_phone(signer.phone))


@router.post(
    "/{token}/sms/verify",
    response_model=PublicEsign,
    summary="Vérifie le code SMS",
)
async def verify_sms_code(
    token: str, data: SmsVerifyRequest, request: Request, db: DBSession
) -> PublicEsign:
    signer, doc = await _load_by_token(db, token)
    if not signer.require_sms_auth:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Aucune vérification SMS requise."
        )
    if signer.sms_verified_at is not None:
        return await _to_public(db, signer, doc)
    if not signer.sms_code_hash or not signer.sms_code_expires_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Aucun code actif — demandez d'abord un code.",
        )
    now = datetime.now(timezone.utc)
    expires = signer.sms_code_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        raise HTTPException(
            status.HTTP_410_GONE,
            "Code expiré — demandez un nouveau code.",
        )
    if (signer.sms_code_attempts or 0) >= _SMS_MAX_ATTEMPTS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Trop d'essais — demandez un nouveau code.",
        )
    supplied = re.sub(r"\D", "", data.code)
    if (
        hashlib.sha256(supplied.encode()).hexdigest()
        != signer.sms_code_hash
    ):
        signer.sms_code_attempts = (signer.sms_code_attempts or 0) + 1
        await db.flush()
        await db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Code incorrect."
        )
    signer.sms_verified_at = now
    signer.sms_code_hash = None
    await db.flush()
    await _add_event(
        db, doc, "sms_verifie", signer=signer, ip=_client_ip(request)
    )
    await db.commit()
    return await _to_public(db, signer, doc)


# --------------------------- Signature / refus ---------------------------


async def _signer_fields(
    db: AsyncSession, doc_id: int, signer_id: int
) -> list[EsignField]:
    return list(
        (
            await db.execute(
                select(EsignField).where(
                    EsignField.document_id == doc_id,
                    EsignField.signer_id == signer_id,
                )
            )
        ).scalars()
    )


@router.post(
    "/{token}/sign",
    response_model=PublicEsign,
    summary="Signe le document",
)
async def sign_esign(
    token: str, data: SignRequest, request: Request, db: DBSession
) -> PublicEsign:
    signer, doc = await _load_by_token(db, token)
    if doc.status != EsignDocumentStatus.ENVOYE.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ce document n'accepte plus de signatures.",
        )
    if signer.signed_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Vous avez déjà signé ce document."
        )
    if signer.declined_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Vous avez refusé ce document."
        )
    if not data.consent:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Vous devez consentir à la signature électronique.",
        )
    signers = await _doc_signers(db, doc.id)
    if not _is_my_turn(doc, signers, signer):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ce n'est pas encore votre tour de signer (signature "
            "séquentielle).",
        )
    if signer.require_sms_auth and signer.sms_verified_at is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Vérifiez d'abord votre identité avec le code SMS.",
        )

    my_fields = await _signer_fields(db, doc.id, signer.id)
    needs_signature = any(
        f.kind == EsignFieldKind.SIGNATURE.value for f in my_fields
    )
    needs_initials = any(
        f.kind == EsignFieldKind.INITIALES.value for f in my_fields
    )
    sig_bytes: Optional[bytes] = None
    ini_bytes: Optional[bytes] = None
    if needs_signature:
        if not data.signature_data_url:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Signature manquante.",
            )
        sig_bytes = _decode_png_data_url(data.signature_data_url, "signature")
    if needs_initials:
        if not data.initials_data_url:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Initiales manquantes.",
            )
        ini_bytes = _decode_png_data_url(data.initials_data_url, "initiales")

    values = {tv.field_id: (tv.value or "").strip() for tv in data.text_values}
    now = datetime.now(timezone.utc)
    for f in my_fields:
        if f.kind == EsignFieldKind.DATE.value:
            f.value_text = date_fr_ca_long(now)
        elif f.kind == EsignFieldKind.TEXTE.value:
            v = values.get(f.id, "")
            if f.required and not v:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Champ requis non rempli : {f.label or 'texte'}.",
                )
            f.value_text = v[:500] or None
        elif f.kind == EsignFieldKind.CASE.value:
            v = values.get(f.id, "")
            checked = v.lower() in ("oui", "true", "1", "on", "x")
            if f.required and not checked:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Case requise non cochée : {f.label or 'case'}.",
                )
            f.value_text = "oui" if checked else None

    if sig_bytes:
        signer.signature_image = sig_bytes
    if ini_bytes:
        signer.initials_image = ini_bytes
    signer.signed_at = now
    signer.signed_ip = _client_ip(request)
    await db.flush()
    await _add_event(
        db, doc, "signe", signer=signer, ip=signer.signed_ip
    )

    all_signed = all(
        s.signed_at is not None
        for s in await _doc_signers(db, doc.id)
    )
    if all_signed:
        doc.status = EsignDocumentStatus.COMPLETE.value
        doc.completed_at = now
        await db.flush()
        await _add_event(db, doc, "complete")

    # IMPORTANT — commit de la signature AVANT la génération du PDF
    # final (cf. bug NDA/Render : un timeout reportlab ne doit jamais
    # coûter la signature).
    await db.commit()

    if all_signed:
        await _finalize_document(db, doc.id)
    elif doc.use_signing_order:
        # Signature séquentielle : invite le(s) prochain(s) signataire(s).
        try:
            fresh_signers = await _doc_signers(db, doc.id)
            ent_name = None
            if doc.entreprise_id:
                ent_name = (
                    await db.execute(
                        select(Entreprise.name).where(
                            Entreprise.id == doc.entreprise_id
                        )
                    )
                ).scalar_one_or_none()
            for nxt in signers_to_invite(doc, fresh_signers):
                if nxt.sent_at is None:
                    try:
                        await send_signer_invitation(db, doc, nxt, ent_name)
                        await _add_event(
                            db, doc, "envoye", signer=nxt, detail=nxt.email
                        )
                    except EsignSendError:
                        log.exception(
                            "eSign : invitation du signataire suivant "
                            "échouée (doc %s)", doc.id,
                        )
            await db.commit()
        except Exception:  # noqa: BLE001
            log.exception(
                "eSign : chaîne séquentielle non relancée (doc %s)", doc.id
            )

    # Notification interne best-effort.
    try:
        from app.services.notifications import notify_role

        await notify_role(
            db,
            min_role="manager",
            kind="esign.signed",
            title=f"eSign : {doc.title}",
            body=(
                f"Signé par {signer.first_name} {signer.last_name}."
                + (" Document complété ✔" if all_signed else "")
            ),
            href="/entreprises/signature",
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        pass

    return await _to_public(db, signer, doc)


async def _finalize_document(db: AsyncSession, doc_id: int) -> None:
    """Génère et stocke le PDF final + envoie les copies. Best-effort :
    la signature DB est déjà commitée, rien ici ne doit lever."""
    try:
        doc = (
            await db.execute(
                select(EsignDocument)
                .where(EsignDocument.id == doc_id)
                .options(
                    undefer(EsignDocument.pdf_blob),
                    undefer(EsignDocument.signed_pdf_blob),
                )
            )
        ).scalar_one()
        signers = list(
            (
                await db.execute(
                    select(EsignSigner)
                    .where(EsignSigner.document_id == doc_id)
                    .options(
                        undefer(EsignSigner.signature_image),
                        undefer(EsignSigner.initials_image),
                    )
                    .order_by(EsignSigner.order_index, EsignSigner.id)
                )
            ).scalars()
        )
        fields = list(
            (
                await db.execute(
                    select(EsignField).where(
                        EsignField.document_id == doc_id
                    )
                )
            ).scalars()
        )
        events = list(
            (
                await db.execute(
                    select(EsignEvent)
                    .where(EsignEvent.document_id == doc_id)
                    .order_by(EsignEvent.created_at, EsignEvent.id)
                )
            ).scalars()
        )
        ent_name = None
        if doc.entreprise_id:
            ent_name = (
                await db.execute(
                    select(Entreprise.name).where(
                        Entreprise.id == doc.entreprise_id
                    )
                )
            ).scalar_one_or_none()

        final_pdf = await asyncio.to_thread(
            build_final_pdf, doc, signers, fields, events, ent_name
        )
        doc.signed_pdf_blob = final_pdf
        await db.flush()
        await db.commit()
        log.info(
            "eSign : PDF final généré pour le doc %s (%d octets)",
            doc_id, len(final_pdf),
        )

        # Copies courriel à toutes les parties + créateur du document
        # + observateurs en copie (V2).
        extra: list[str] = []
        try:
            if doc.created_by_user_id:
                from app.models.user import User

                creator_email = (
                    await db.execute(
                        select(User.email).where(
                            User.id == doc.created_by_user_id
                        )
                    )
                ).scalar_one_or_none()
                if creator_email:
                    extra.append(creator_email)
        except Exception:  # noqa: BLE001
            pass
        try:
            observer_emails = (
                await db.execute(
                    select(EsignObserver.email).where(
                        EsignObserver.document_id == doc_id
                    )
                )
            ).scalars().all()
            extra.extend(observer_emails)
        except Exception:  # noqa: BLE001
            pass
        await send_completion_emails(
            doc, signers, final_pdf, final_pdf_filename(doc), extra
        )
    except Exception:  # noqa: BLE001
        log.exception(
            "eSign : finalisation du doc %s échouée — signatures "
            "conservées en DB, PDF final regénérable.", doc_id,
        )


@router.post(
    "/{token}/decline",
    response_model=PublicEsign,
    summary="Refuse de signer (avec raison facultative)",
)
async def decline_esign(
    token: str, data: DeclineRequest, request: Request, db: DBSession
) -> PublicEsign:
    signer, doc = await _load_by_token(db, token)
    if doc.status != EsignDocumentStatus.ENVOYE.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ce document n'accepte plus de réponses.",
        )
    if signer.signed_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Vous avez déjà signé ce document."
        )
    if signer.declined_at:
        return await _to_public(db, signer, doc)

    now = datetime.now(timezone.utc)
    signer.declined_at = now
    signer.decline_reason = (data.reason or "").strip()[:1000] or None
    doc.status = EsignDocumentStatus.REFUSE.value
    await db.flush()
    await _add_event(
        db, doc, "refuse", signer=signer, ip=_client_ip(request),
        detail=signer.decline_reason,
    )
    await db.commit()

    try:
        from app.services.notifications import notify_role

        await notify_role(
            db,
            min_role="manager",
            kind="esign.declined",
            title=f"eSign : refus — {doc.title}",
            body=(
                f"{signer.first_name} {signer.last_name} a refusé de signer."
                + (f" Raison : {signer.decline_reason}"
                   if signer.decline_reason else "")
            ),
            href="/entreprises/signature",
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        pass

    return await _to_public(db, signer, doc)
