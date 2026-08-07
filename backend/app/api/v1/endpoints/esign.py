"""eSign — endpoints ADMIN (pôle Gestion d'entreprise → Signature).

Flow :
    POST   /esign/documents                    téléverse un PDF (brouillon)
    GET    /esign/documents?group=en_cours     liste (en cours / signés)
    GET    /esign/documents/{id}               détail (signataires, zones, journal)
    PATCH  /esign/documents/{id}               titre / message / entreprise / ordre
    DELETE /esign/documents/{id}               suppression (brouillon / annulé)
    GET    /esign/documents/{id}/pdf           PDF original inline
    GET    /esign/documents/{id}/signed-pdf    PDF final aplati
    GET    /esign/documents/{id}/pages/{n}     page rendue en PNG (éditeur visuel)
    POST   /esign/documents/{id}/signers       ajoute un signataire (brouillon)
    PATCH  /esign/signers/{id}                 modifie un signataire (brouillon)
    DELETE /esign/signers/{id}                 retire un signataire (brouillon)
    PUT    /esign/documents/{id}/fields        remplace les zones (brouillon)
    POST   /esign/documents/{id}/send          envoie les invitations
    POST   /esign/documents/{id}/remind        relance les signataires en attente
    POST   /esign/documents/{id}/cancel        annule le document

V2 :
    POST   /esign/documents/{id}/observers     ajoute un observateur CC (brouillon)
    DELETE /esign/observers/{id}               retire un observateur (brouillon)
    POST   /esign/documents/{id}/attachments   ajoute une annexe PDF (brouillon)
    DELETE /esign/attachments/{id}             retire une annexe (brouillon)
    GET    /esign/attachments/{id}/pdf         télécharge une annexe
    POST   /esign/documents/{id}/save-as-template   snapshot → modèle réutilisable
    GET    /esign/templates                    liste des modèles
    GET    /esign/templates/{id}               détail (rôles)
    DELETE /esign/templates/{id}               supprime un modèle
    POST   /esign/documents/from-template      instancie un brouillon complet

Registered dans router.py avec DEP_ENTREPRISES ; la page frontend est
`/entreprises/signature` (clé d'accès `entreprises.signature`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date as date_type
from datetime import datetime, time as time_type, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.api.deps import CurrentUser, DBSession
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
    EsignTemplate,
    EsignTemplateField,
)
from app.services.esign_pdf import (
    final_pdf_filename,
    page_png,
    pdf_page_count,
)
from app.services.esign_send import (
    EsignSendError,
    ensure_token,
    send_observer_notice,
    send_signer_invitation,
    signers_to_invite,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/esign", tags=["esign"])

_PDF_MAX_BYTES = 25 * 1024 * 1024
_ATTACHMENT_MAX_BYTES = 15 * 1024 * 1024
_ATTACHMENTS_MAX_COUNT = 10
_FIELD_KINDS = {k.value for k in EsignFieldKind}
_PAGE_DPI = 130
_TZ_MONTREAL = ZoneInfo("America/Toronto")


# --------------------------- Schemas ---------------------------


class SignerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_ref: Optional[str]
    order_index: int
    first_name: str
    last_name: str
    email: str
    phone: Optional[str]
    require_sms_auth: bool
    sms_verified_at: Optional[datetime]
    sent_at: Optional[datetime]
    opened_at: Optional[datetime]
    last_opened_at: Optional[datetime]
    open_count: int
    signed_at: Optional[datetime]
    signed_ip: Optional[str]
    declined_at: Optional[datetime]
    decline_reason: Optional[str]


class FieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    signer_id: int
    kind: str
    page: int
    x: float
    y: float
    w: float
    h: float
    required: bool
    label: Optional[str]
    value_text: Optional[str]


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    signer_id: Optional[int]
    type: str
    ip: Optional[str]
    detail: Optional[str]
    created_at: datetime


class ObserverRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    size_bytes: int


class DocumentListItem(BaseModel):
    id: int
    title: str
    status: str
    entreprise_id: Optional[int]
    entreprise_name: Optional[str]
    filename: str
    page_count: int
    use_signing_order: bool
    sent_at: Optional[datetime]
    completed_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]
    signers: List[SignerRead]


class DocumentDetail(DocumentListItem):
    message: Optional[str]
    sha256: Optional[str]
    reminder_days: Optional[int]
    has_signed_pdf: bool
    fields: List[FieldRead]
    events: List[EventRead]
    observers: List[ObserverRead]
    attachments: List[AttachmentRead]


class DocumentPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    message: Optional[str] = Field(default=None, max_length=5000)
    entreprise_id: Optional[int] = None
    use_signing_order: Optional[bool] = None
    # V2 — "YYYY-MM-DD" (fin de journée à Montréal) ou "" pour retirer.
    expires_on: Optional[str] = Field(default=None, max_length=10)
    # V2 — 1..30 jours, 0 ou null pour désactiver.
    reminder_days: Optional[int] = Field(default=None, ge=0, le=30)


class ObserverCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr


class TemplateRole(BaseModel):
    name: str
    require_sms_auth: bool = False


class TemplateListItem(BaseModel):
    id: int
    title: str
    entreprise_id: Optional[int]
    entreprise_name: Optional[str]
    filename: str
    page_count: int
    use_signing_order: bool
    roles: List[TemplateRole]
    field_count: int
    created_at: datetime


class SaveTemplateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)


class FromTemplateRequest(BaseModel):
    template_id: int
    title: Optional[str] = Field(default=None, max_length=255)
    entreprise_id: Optional[int] = None
    # Un signataire par rôle du modèle, dans l'ordre.
    signers: List[SignerCreate]


class SignerCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=32)
    require_sms_auth: bool = False
    order_index: int = 0
    contact_ref: Optional[str] = Field(default=None, max_length=64)


class SignerPatch(BaseModel):
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=32)
    require_sms_auth: Optional[bool] = None
    order_index: Optional[int] = None


class FieldWrite(BaseModel):
    signer_id: int
    kind: str
    page: int = Field(..., ge=1)
    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    w: float = Field(..., gt=0.0, le=1.0)
    h: float = Field(..., gt=0.0, le=1.0)
    required: bool = True
    label: Optional[str] = Field(default=None, max_length=120)


class SendResult(BaseModel):
    sent: int
    errors: List[str]


# --------------------------- Helpers ---------------------------


async def _load_doc(db, doc_id: int, *, with_blob: bool = False) -> EsignDocument:
    stmt = select(EsignDocument).where(EsignDocument.id == doc_id)
    if with_blob:
        stmt = stmt.options(undefer(EsignDocument.pdf_blob))
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document introuvable.")
    return doc


async def _load_signers(db, doc_id: int) -> list[EsignSigner]:
    return list(
        (
            await db.execute(
                select(EsignSigner)
                .where(EsignSigner.document_id == doc_id)
                .order_by(EsignSigner.order_index, EsignSigner.id)
            )
        ).scalars()
    )


async def _entreprise_name(db, entreprise_id: Optional[int]) -> Optional[str]:
    if not entreprise_id:
        return None
    ent = (
        await db.execute(
            select(Entreprise.name).where(Entreprise.id == entreprise_id)
        )
    ).scalar_one_or_none()
    return ent


def _require_draft(doc: EsignDocument) -> None:
    if doc.status != EsignDocumentStatus.BROUILLON.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Modifiable uniquement en brouillon (le document a déjà été "
            "envoyé).",
        )


async def _add_event(
    db,
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


async def _doc_to_list_item(db, doc: EsignDocument) -> DocumentListItem:
    return DocumentListItem(
        id=doc.id,
        title=doc.title,
        status=doc.status,
        entreprise_id=doc.entreprise_id,
        entreprise_name=await _entreprise_name(db, doc.entreprise_id),
        filename=doc.filename,
        page_count=doc.page_count,
        use_signing_order=doc.use_signing_order,
        sent_at=doc.sent_at,
        completed_at=doc.completed_at,
        expires_at=doc.expires_at,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        signers=[
            SignerRead.model_validate(s) for s in await _load_signers(db, doc.id)
        ],
    )


async def _doc_to_detail(db, doc: EsignDocument) -> DocumentDetail:
    base = await _doc_to_list_item(db, doc)
    fields = list(
        (
            await db.execute(
                select(EsignField)
                .where(EsignField.document_id == doc.id)
                .order_by(EsignField.page, EsignField.id)
            )
        ).scalars()
    )
    events = list(
        (
            await db.execute(
                select(EsignEvent)
                .where(EsignEvent.document_id == doc.id)
                .order_by(EsignEvent.created_at.desc(), EsignEvent.id.desc())
                .limit(200)
            )
        ).scalars()
    )
    has_signed = (
        await db.execute(
            select(EsignDocument.id)
            .where(
                EsignDocument.id == doc.id,
                EsignDocument.signed_pdf_blob.isnot(None),
            )
        )
    ).scalar_one_or_none() is not None
    observers = list(
        (
            await db.execute(
                select(EsignObserver)
                .where(EsignObserver.document_id == doc.id)
                .order_by(EsignObserver.id)
            )
        ).scalars()
    )
    attachments = list(
        (
            await db.execute(
                select(EsignAttachment)
                .where(EsignAttachment.document_id == doc.id)
                .order_by(EsignAttachment.id)
            )
        ).scalars()
    )
    return DocumentDetail(
        **base.model_dump(),
        message=doc.message,
        sha256=doc.sha256,
        reminder_days=doc.reminder_days,
        has_signed_pdf=has_signed,
        fields=[FieldRead.model_validate(f) for f in fields],
        events=[EventRead.model_validate(e) for e in events],
        observers=[ObserverRead.model_validate(o) for o in observers],
        attachments=[AttachmentRead.model_validate(a) for a in attachments],
    )


# --------------------------- Documents ---------------------------


@router.post(
    "/documents",
    response_model=DocumentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Téléverse un PDF à faire signer (brouillon)",
)
async def create_document(
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    entreprise_id: Optional[int] = Form(default=None),
) -> DocumentDetail:
    ct = (file.content_type or "").lower()
    if ct != "application/pdf":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Seuls les fichiers PDF sont acceptés.",
        )
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")
    if len(blob) > _PDF_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "PDF trop volumineux (max 25 Mo).",
        )
    try:
        pages = await asyncio.to_thread(pdf_page_count, blob)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"PDF illisible : {exc}",
        ) from exc

    filename = (file.filename or "document.pdf")[:255]
    doc = EsignDocument(
        entreprise_id=entreprise_id or None,
        created_by_user_id=user.id,
        title=(title or "").strip()[:255] or filename.rsplit(".", 1)[0][:255],
        filename=filename,
        content_type="application/pdf",
        pdf_blob=blob,
        page_count=pages,
        sha256=hashlib.sha256(blob).hexdigest(),
    )
    db.add(doc)
    await db.flush()
    await _add_event(db, doc, "cree", detail=f"par {user.email}")
    await db.refresh(doc)
    return await _doc_to_detail(db, doc)


@router.get(
    "/documents",
    response_model=List[DocumentListItem],
    summary="Liste des documents (en cours / signés / tous)",
)
async def list_documents(
    db: DBSession,
    user: CurrentUser,
    group: Optional[str] = None,
    entreprise_id: Optional[int] = None,
    q: Optional[str] = None,
) -> List[DocumentListItem]:
    stmt = select(EsignDocument)
    if group == "en_cours":
        stmt = stmt.where(
            EsignDocument.status.in_(
                [
                    EsignDocumentStatus.BROUILLON.value,
                    EsignDocumentStatus.ENVOYE.value,
                    EsignDocumentStatus.REFUSE.value,
                    EsignDocumentStatus.EXPIRE.value,
                ]
            )
        )
    elif group == "signes":
        stmt = stmt.where(
            EsignDocument.status == EsignDocumentStatus.COMPLETE.value
        )
    if entreprise_id:
        stmt = stmt.where(EsignDocument.entreprise_id == entreprise_id)
    if q and q.strip():
        stmt = stmt.where(EsignDocument.title.ilike(f"%{q.strip()}%"))
    stmt = stmt.order_by(EsignDocument.updated_at.desc().nullslast(),
                         EsignDocument.id.desc()).limit(300)
    docs = list((await db.execute(stmt)).scalars())
    return [await _doc_to_list_item(db, d) for d in docs]


@router.get(
    "/documents/{doc_id}",
    response_model=DocumentDetail,
    summary="Détail d'un document (signataires, zones, journal)",
)
async def read_document(
    doc_id: int, db: DBSession, user: CurrentUser
) -> DocumentDetail:
    doc = await _load_doc(db, doc_id)
    return await _doc_to_detail(db, doc)


@router.patch(
    "/documents/{doc_id}",
    response_model=DocumentDetail,
    summary="Modifie titre / message / entreprise / ordre de signature",
)
async def patch_document(
    doc_id: int, data: DocumentPatch, db: DBSession, user: CurrentUser
) -> DocumentDetail:
    doc = await _load_doc(db, doc_id)
    if data.title is not None:
        doc.title = data.title.strip()[:255]
    if data.message is not None:
        doc.message = data.message.strip() or None
    if data.entreprise_id is not None:
        doc.entreprise_id = data.entreprise_id or None
    if data.use_signing_order is not None:
        _require_draft(doc)
        doc.use_signing_order = bool(data.use_signing_order)
    if "expires_on" in data.model_fields_set:
        raw = (data.expires_on or "").strip()
        if not raw:
            doc.expires_at = None
        else:
            try:
                d = date_type.fromisoformat(raw)
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Date d'expiration invalide (format AAAA-MM-JJ).",
                ) from exc
            # Fin de journée à Montréal → le lien reste valide toute la
            # journée choisie.
            doc.expires_at = datetime.combine(
                d, time_type(23, 59, 59), tzinfo=_TZ_MONTREAL
            ).astimezone(timezone.utc)
    if "reminder_days" in data.model_fields_set:
        doc.reminder_days = data.reminder_days or None
    await db.flush()
    return await _doc_to_detail(db, doc)


@router.delete(
    "/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprime un document (brouillon ou annulé seulement)",
)
async def delete_document(
    doc_id: int, db: DBSession, user: CurrentUser
) -> Response:
    doc = await _load_doc(db, doc_id)
    if doc.status not in (
        EsignDocumentStatus.BROUILLON.value,
        EsignDocumentStatus.ANNULE.value,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Annulez d'abord le document avant de le supprimer.",
        )
    await db.delete(doc)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/documents/{doc_id}/pdf", summary="PDF original inline")
async def document_pdf(
    doc_id: int, db: DBSession, user: CurrentUser
) -> Response:
    doc = await _load_doc(db, doc_id, with_blob=True)
    return Response(
        content=bytes(doc.pdf_blob),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{doc.filename}"'
        },
    )


@router.get(
    "/documents/{doc_id}/signed-pdf",
    summary="PDF final aplati (zones fusionnées + certificat)",
)
async def document_signed_pdf(
    doc_id: int, db: DBSession, user: CurrentUser
) -> Response:
    doc = (
        await db.execute(
            select(EsignDocument)
            .where(EsignDocument.id == doc_id)
            .options(undefer(EsignDocument.signed_pdf_blob))
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document introuvable.")
    if not doc.signed_pdf_blob:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "PDF final pas encore disponible (document non complété).",
        )
    return Response(
        content=bytes(doc.signed_pdf_blob),
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'inline; filename="{final_pdf_filename(doc)}"'
        },
    )


@router.get(
    "/documents/{doc_id}/pages/{page_number}",
    summary="Page du PDF rendue en PNG (éditeur de zones)",
)
async def document_page_png(
    doc_id: int, page_number: int, db: DBSession, user: CurrentUser
) -> Response:
    doc = await _load_doc(db, doc_id, with_blob=True)
    if page_number < 1 or page_number > max(doc.page_count, 1):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page hors limites.")
    try:
        png = await asyncio.to_thread(
            page_png, bytes(doc.pdf_blob), page_number, _PAGE_DPI
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("eSign : rendu page %s du doc %s échoué",
                      page_number, doc_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Rendu de page échoué : {exc}"
        ) from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


# --------------------------- Signataires ---------------------------


@router.post(
    "/documents/{doc_id}/signers",
    response_model=SignerRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ajoute un signataire (banque de contacts ou manuel)",
)
async def add_signer(
    doc_id: int, data: SignerCreate, db: DBSession, user: CurrentUser
) -> SignerRead:
    doc = await _load_doc(db, doc_id)
    _require_draft(doc)
    if data.require_sms_auth and not (data.phone or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Numéro de téléphone requis pour l'authentification SMS.",
        )
    signer = EsignSigner(
        document_id=doc.id,
        contact_ref=(data.contact_ref or None),
        order_index=max(0, data.order_index),
        first_name=data.first_name.strip()[:100],
        last_name=data.last_name.strip()[:100],
        email=str(data.email).strip().lower()[:320],
        phone=(data.phone or "").strip()[:32] or None,
        require_sms_auth=data.require_sms_auth,
    )
    db.add(signer)
    await db.flush()
    await db.refresh(signer)
    return SignerRead.model_validate(signer)


@router.patch(
    "/signers/{signer_id}",
    response_model=SignerRead,
    summary="Modifie un signataire (brouillon)",
)
async def patch_signer(
    signer_id: int, data: SignerPatch, db: DBSession, user: CurrentUser
) -> SignerRead:
    signer = (
        await db.execute(
            select(EsignSigner).where(EsignSigner.id == signer_id)
        )
    ).scalar_one_or_none()
    if signer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Signataire introuvable.")
    doc = await _load_doc(db, signer.document_id)
    _require_draft(doc)
    if data.first_name is not None:
        signer.first_name = data.first_name.strip()[:100]
    if data.last_name is not None:
        signer.last_name = data.last_name.strip()[:100]
    if data.email is not None:
        signer.email = str(data.email).strip().lower()[:320]
    if data.phone is not None:
        signer.phone = data.phone.strip()[:32] or None
    if data.require_sms_auth is not None:
        signer.require_sms_auth = bool(data.require_sms_auth)
    if data.order_index is not None:
        signer.order_index = max(0, data.order_index)
    if signer.require_sms_auth and not (signer.phone or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Numéro de téléphone requis pour l'authentification SMS.",
        )
    await db.flush()
    await db.refresh(signer)
    return SignerRead.model_validate(signer)


@router.delete(
    "/signers/{signer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire un signataire (brouillon)",
)
async def delete_signer(
    signer_id: int, db: DBSession, user: CurrentUser
) -> Response:
    signer = (
        await db.execute(
            select(EsignSigner).where(EsignSigner.id == signer_id)
        )
    ).scalar_one_or_none()
    if signer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Signataire introuvable.")
    doc = await _load_doc(db, signer.document_id)
    _require_draft(doc)
    await db.delete(signer)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------- Zones ---------------------------


@router.put(
    "/documents/{doc_id}/fields",
    response_model=List[FieldRead],
    summary="Remplace toutes les zones du document (brouillon)",
)
async def replace_fields(
    doc_id: int, data: List[FieldWrite], db: DBSession, user: CurrentUser
) -> List[FieldRead]:
    doc = await _load_doc(db, doc_id)
    _require_draft(doc)
    signer_ids = {s.id for s in await _load_signers(db, doc_id)}
    for fw in data:
        if fw.kind not in _FIELD_KINDS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Type de zone inconnu : {fw.kind}",
            )
        if fw.signer_id not in signer_ids:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Zone assignée à un signataire qui n'est pas sur ce document.",
            )
        if fw.page > max(doc.page_count, 1):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Page {fw.page} hors limites ({doc.page_count} pages).",
            )
    existing = list(
        (
            await db.execute(
                select(EsignField).where(EsignField.document_id == doc_id)
            )
        ).scalars()
    )
    for f in existing:
        await db.delete(f)
    await db.flush()
    created: list[EsignField] = []
    for fw in data:
        f = EsignField(
            document_id=doc_id,
            signer_id=fw.signer_id,
            kind=fw.kind,
            page=fw.page,
            x=min(max(fw.x, 0.0), 1.0),
            y=min(max(fw.y, 0.0), 1.0),
            w=min(fw.w, 1.0),
            h=min(fw.h, 1.0),
            required=fw.required,
            label=(fw.label or "").strip()[:120] or None,
        )
        db.add(f)
        created.append(f)
    await db.flush()
    for f in created:
        await db.refresh(f)
    return [FieldRead.model_validate(f) for f in created]


# --------------------------- Envoi / relance / annulation -----------


@router.post(
    "/documents/{doc_id}/send",
    response_model=SendResult,
    summary="Envoie les invitations de signature",
)
async def send_document(
    doc_id: int, db: DBSession, user: CurrentUser
) -> SendResult:
    doc = await _load_doc(db, doc_id)
    if doc.status not in (
        EsignDocumentStatus.BROUILLON.value,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Document déjà envoyé — utilisez la relance.",
        )
    if doc.expires_at is not None and doc.expires_at <= datetime.now(
        timezone.utc
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "La date d'expiration est déjà passée — corrigez-la avant "
            "d'envoyer.",
        )
    signers = await _load_signers(db, doc_id)
    if not signers:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Ajoutez au moins un signataire avant d'envoyer.",
        )
    fields = list(
        (
            await db.execute(
                select(EsignField).where(EsignField.document_id == doc_id)
            )
        ).scalars()
    )
    by_signer: dict[int, int] = {}
    for f in fields:
        by_signer[f.signer_id] = by_signer.get(f.signer_id, 0) + 1
    missing = [s for s in signers if not by_signer.get(s.id)]
    if missing:
        names = ", ".join(
            f"{s.first_name} {s.last_name}".strip() for s in missing
        )
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Aucune zone placée pour : {names}. Chaque signataire doit "
            "avoir au moins une zone (signature, initiales, date ou texte).",
        )
    for s in signers:
        if s.require_sms_auth and not (s.phone or "").strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Téléphone manquant pour {s.first_name} {s.last_name} "
                "(authentification SMS activée).",
            )
        ensure_token(s)
    await db.flush()

    ent_name = await _entreprise_name(db, doc.entreprise_id)
    invitees = signers_to_invite(doc, signers)
    sent = 0
    errors: list[str] = []
    for s in invitees:
        try:
            await send_signer_invitation(db, doc, s, ent_name)
            await _add_event(db, doc, "envoye", signer=s, detail=s.email)
            sent += 1
        except EsignSendError as exc:
            errors.append(f"{s.email} : {exc}")
    if sent == 0:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Aucune invitation n'a pu être envoyée : "
            + " / ".join(errors),
        )
    doc.status = EsignDocumentStatus.ENVOYE.value
    doc.sent_at = datetime.now(timezone.utc)
    await db.flush()

    # Avis aux observateurs en copie (best-effort, non bloquant).
    observers = list(
        (
            await db.execute(
                select(EsignObserver).where(
                    EsignObserver.document_id == doc_id
                )
            )
        ).scalars()
    )
    signer_names = [
        f"{s.first_name} {s.last_name}".strip() for s in signers
    ]
    for obs in observers:
        await send_observer_notice(
            doc, obs.name, obs.email, signer_names, ent_name
        )

    return SendResult(sent=sent, errors=errors)


@router.post(
    "/documents/{doc_id}/remind",
    response_model=SendResult,
    summary="Relance les signataires en attente",
)
async def remind_document(
    doc_id: int, db: DBSession, user: CurrentUser
) -> SendResult:
    doc = await _load_doc(db, doc_id)
    if doc.status != EsignDocumentStatus.ENVOYE.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Relance possible uniquement pour un document en cours.",
        )
    signers = await _load_signers(db, doc_id)
    ent_name = await _entreprise_name(db, doc.entreprise_id)
    sent = 0
    errors: list[str] = []
    for s in signers_to_invite(doc, signers):
        try:
            await send_signer_invitation(db, doc, s, ent_name, reminder=True)
            # Une relance manuelle remet à zéro l'horloge des rappels
            # automatiques du cron.
            s.last_reminder_at = datetime.now(timezone.utc)
            await _add_event(db, doc, "relance", signer=s, detail=s.email)
            sent += 1
        except EsignSendError as exc:
            errors.append(f"{s.email} : {exc}")
    if sent == 0 and errors:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Relance échouée : " + " / ".join(errors),
        )
    return SendResult(sent=sent, errors=errors)


@router.post(
    "/documents/{doc_id}/cancel",
    response_model=DocumentDetail,
    summary="Annule le document (désactive les liens publics)",
)
async def cancel_document(
    doc_id: int, db: DBSession, user: CurrentUser
) -> DocumentDetail:
    doc = await _load_doc(db, doc_id)
    if doc.status in (
        EsignDocumentStatus.COMPLETE.value,
        EsignDocumentStatus.ANNULE.value,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Document déjà complété ou annulé.",
        )
    doc.status = EsignDocumentStatus.ANNULE.value
    await db.flush()
    await _add_event(db, doc, "annule", detail=f"par {user.email}")
    return await _doc_to_detail(db, doc)


# --------------------------- Observateurs (V2) ---------------------------


@router.post(
    "/documents/{doc_id}/observers",
    response_model=ObserverRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ajoute un observateur en copie (ne signe pas)",
)
async def add_observer(
    doc_id: int, data: ObserverCreate, db: DBSession, user: CurrentUser
) -> ObserverRead:
    doc = await _load_doc(db, doc_id)
    _require_draft(doc)
    obs = EsignObserver(
        document_id=doc.id,
        name=data.name.strip()[:200],
        email=str(data.email).strip().lower()[:320],
    )
    db.add(obs)
    await db.flush()
    await db.refresh(obs)
    return ObserverRead.model_validate(obs)


@router.delete(
    "/observers/{observer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire un observateur (brouillon)",
)
async def delete_observer(
    observer_id: int, db: DBSession, user: CurrentUser
) -> Response:
    obs = (
        await db.execute(
            select(EsignObserver).where(EsignObserver.id == observer_id)
        )
    ).scalar_one_or_none()
    if obs is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Observateur introuvable."
        )
    doc = await _load_doc(db, obs.document_id)
    _require_draft(doc)
    await db.delete(obs)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------- Annexes (V2) ---------------------------


@router.post(
    "/documents/{doc_id}/attachments",
    response_model=AttachmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ajoute une annexe PDF consultable (non signée)",
)
async def add_attachment(
    doc_id: int,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> AttachmentRead:
    doc = await _load_doc(db, doc_id)
    _require_draft(doc)
    ct = (file.content_type or "").lower()
    if ct != "application/pdf":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Seuls les fichiers PDF sont acceptés en annexe.",
        )
    count = (
        await db.execute(
            select(EsignAttachment.id).where(
                EsignAttachment.document_id == doc_id
            )
        )
    ).scalars().all()
    if len(count) >= _ATTACHMENTS_MAX_COUNT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Maximum {_ATTACHMENTS_MAX_COUNT} annexes par document.",
        )
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")
    if len(blob) > _ATTACHMENT_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Annexe trop volumineuse (max 15 Mo).",
        )
    att = EsignAttachment(
        document_id=doc.id,
        filename=(file.filename or "annexe.pdf")[:255],
        content_type="application/pdf",
        blob=blob,
        size_bytes=len(blob),
    )
    db.add(att)
    await db.flush()
    await db.refresh(att)
    return AttachmentRead.model_validate(att)


@router.delete(
    "/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire une annexe (brouillon)",
)
async def delete_attachment(
    attachment_id: int, db: DBSession, user: CurrentUser
) -> Response:
    att = (
        await db.execute(
            select(EsignAttachment).where(
                EsignAttachment.id == attachment_id
            )
        )
    ).scalar_one_or_none()
    if att is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annexe introuvable.")
    doc = await _load_doc(db, att.document_id)
    _require_draft(doc)
    await db.delete(att)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/attachments/{attachment_id}/pdf",
    summary="Télécharge une annexe",
)
async def attachment_pdf(
    attachment_id: int, db: DBSession, user: CurrentUser
) -> Response:
    att = (
        await db.execute(
            select(EsignAttachment)
            .where(EsignAttachment.id == attachment_id)
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


# --------------------------- Modèles (V2) ---------------------------


def _parse_roles(tpl: EsignTemplate) -> list[TemplateRole]:
    try:
        raw = json.loads(tpl.roles_json or "[]")
        return [
            TemplateRole(
                name=str(r.get("name") or f"Signataire {i + 1}"),
                require_sms_auth=bool(r.get("require_sms_auth")),
            )
            for i, r in enumerate(raw)
        ]
    except Exception:  # noqa: BLE001
        return []


async def _template_to_item(
    db, tpl: EsignTemplate
) -> TemplateListItem:
    field_count = len(
        (
            await db.execute(
                select(EsignTemplateField.id).where(
                    EsignTemplateField.template_id == tpl.id
                )
            )
        ).scalars().all()
    )
    return TemplateListItem(
        id=tpl.id,
        title=tpl.title,
        entreprise_id=tpl.entreprise_id,
        entreprise_name=await _entreprise_name(db, tpl.entreprise_id),
        filename=tpl.filename,
        page_count=tpl.page_count,
        use_signing_order=tpl.use_signing_order,
        roles=_parse_roles(tpl),
        field_count=field_count,
        created_at=tpl.created_at,
    )


@router.post(
    "/documents/{doc_id}/save-as-template",
    response_model=TemplateListItem,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistre le document (PDF + zones) comme modèle réutilisable",
)
async def save_as_template(
    doc_id: int,
    data: SaveTemplateRequest,
    db: DBSession,
    user: CurrentUser,
) -> TemplateListItem:
    doc = await _load_doc(db, doc_id, with_blob=True)
    signers = await _load_signers(db, doc_id)
    if not signers:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Ajoutez au moins un signataire avant d'enregistrer un modèle "
            "(les zones sont liées aux rôles).",
        )
    fields = list(
        (
            await db.execute(
                select(EsignField).where(EsignField.document_id == doc_id)
            )
        ).scalars()
    )
    if not fields:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Placez au moins une zone avant d'enregistrer un modèle.",
        )
    role_index_by_signer = {s.id: i for i, s in enumerate(signers)}
    roles = [
        {
            "name": f"Signataire {i + 1}",
            "require_sms_auth": s.require_sms_auth,
        }
        for i, s in enumerate(signers)
    ]
    tpl = EsignTemplate(
        entreprise_id=doc.entreprise_id,
        created_by_user_id=user.id,
        title=(data.title or "").strip()[:255] or f"Modèle — {doc.title}",
        message=doc.message,
        use_signing_order=doc.use_signing_order,
        filename=doc.filename,
        content_type="application/pdf",
        pdf_blob=bytes(doc.pdf_blob),
        page_count=doc.page_count,
        sha256=doc.sha256,
        roles_json=json.dumps(roles, ensure_ascii=False),
    )
    db.add(tpl)
    await db.flush()
    for f in fields:
        db.add(
            EsignTemplateField(
                template_id=tpl.id,
                role_index=role_index_by_signer.get(f.signer_id, 0),
                kind=f.kind,
                page=f.page,
                x=f.x,
                y=f.y,
                w=f.w,
                h=f.h,
                required=f.required,
                label=f.label,
            )
        )
    await db.flush()
    await db.refresh(tpl)
    return await _template_to_item(db, tpl)


@router.get(
    "/templates",
    response_model=List[TemplateListItem],
    summary="Liste des modèles réutilisables",
)
async def list_templates(
    db: DBSession, user: CurrentUser
) -> List[TemplateListItem]:
    tpls = list(
        (
            await db.execute(
                select(EsignTemplate).order_by(EsignTemplate.id.desc())
            )
        ).scalars()
    )
    return [await _template_to_item(db, t) for t in tpls]


@router.get(
    "/templates/{template_id}",
    response_model=TemplateListItem,
    summary="Détail d'un modèle (rôles)",
)
async def read_template(
    template_id: int, db: DBSession, user: CurrentUser
) -> TemplateListItem:
    tpl = (
        await db.execute(
            select(EsignTemplate).where(EsignTemplate.id == template_id)
        )
    ).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modèle introuvable.")
    return await _template_to_item(db, tpl)


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprime un modèle",
)
async def delete_template(
    template_id: int, db: DBSession, user: CurrentUser
) -> Response:
    tpl = (
        await db.execute(
            select(EsignTemplate).where(EsignTemplate.id == template_id)
        )
    ).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modèle introuvable.")
    await db.delete(tpl)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/documents/from-template",
    response_model=DocumentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Crée un brouillon complet à partir d'un modèle",
)
async def create_from_template(
    data: FromTemplateRequest, db: DBSession, user: CurrentUser
) -> DocumentDetail:
    tpl = (
        await db.execute(
            select(EsignTemplate)
            .where(EsignTemplate.id == data.template_id)
            .options(undefer(EsignTemplate.pdf_blob))
        )
    ).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modèle introuvable.")
    roles = _parse_roles(tpl)
    if len(data.signers) != len(roles):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Ce modèle attend {len(roles)} signataire(s) "
            f"({len(data.signers)} fourni(s)).",
        )
    for i, sc in enumerate(data.signers):
        if sc.require_sms_auth and not (sc.phone or "").strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Téléphone manquant pour {sc.first_name} {sc.last_name} "
                "(authentification SMS activée).",
            )

    doc = EsignDocument(
        entreprise_id=(
            data.entreprise_id
            if data.entreprise_id is not None
            else tpl.entreprise_id
        ) or None,
        created_by_user_id=user.id,
        title=(data.title or "").strip()[:255] or tpl.title,
        message=tpl.message,
        use_signing_order=tpl.use_signing_order,
        filename=tpl.filename,
        content_type="application/pdf",
        pdf_blob=bytes(tpl.pdf_blob),
        page_count=tpl.page_count,
        sha256=tpl.sha256,
    )
    db.add(doc)
    await db.flush()

    created_signers: list[EsignSigner] = []
    for i, sc in enumerate(data.signers):
        signer = EsignSigner(
            document_id=doc.id,
            contact_ref=(sc.contact_ref or None),
            order_index=i,
            first_name=sc.first_name.strip()[:100],
            last_name=sc.last_name.strip()[:100],
            email=str(sc.email).strip().lower()[:320],
            phone=(sc.phone or "").strip()[:32] or None,
            require_sms_auth=sc.require_sms_auth,
        )
        db.add(signer)
        created_signers.append(signer)
    await db.flush()

    tpl_fields = list(
        (
            await db.execute(
                select(EsignTemplateField).where(
                    EsignTemplateField.template_id == tpl.id
                )
            )
        ).scalars()
    )
    for tf in tpl_fields:
        idx = min(max(tf.role_index, 0), len(created_signers) - 1)
        db.add(
            EsignField(
                document_id=doc.id,
                signer_id=created_signers[idx].id,
                kind=tf.kind,
                page=tf.page,
                x=tf.x,
                y=tf.y,
                w=tf.w,
                h=tf.h,
                required=tf.required,
                label=tf.label,
            )
        )
    await db.flush()
    await _add_event(
        db, doc, "cree",
        detail=f"depuis le modèle « {tpl.title} » par {user.email}",
    )
    await db.refresh(doc)
    return await _doc_to_detail(db, doc)
