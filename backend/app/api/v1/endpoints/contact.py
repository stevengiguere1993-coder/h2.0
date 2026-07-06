"""
Contact request endpoints.
"""

from typing import List, Optional

from datetime import datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.contact_request import ContactRequestStatus, ProjectType
from app.models.contact_request_photo import ContactRequestPhoto
from app.schemas.contact_request import (
    ContactRequestCreate,
    ContactRequestPublicAck,
    ContactRequestRead,
    ContactRequestUpdate,
)
from app.services.contact_request import ContactRequestService


router = APIRouter(prefix="/contact", tags=["contact"])

MAX_PHOTOS = 5
MAX_PHOTO_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    # Staff upload path accepts PDFs too (plans, devis concurrents,
    # anciennes factures) — the public form still filters client-side
    # to image/* for safety.
    "application/pdf",
}


@router.post(
    "",
    response_model=ContactRequestPublicAck,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a contact request (public, multipart/form-data)",
)
async def submit_contact(
    request: Request,
    db: DBSession,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    email: str = Form(...),
    message: str = Form(...),
    gdpr_consent: bool = Form(...),
    phone: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    project_type: str = Form("autre"),
    budget_range: Optional[str] = Form(None),
    locale: str = Form("fr"),
    source: Optional[str] = Form(None),
    marketing_consent: bool = Form(False),
    # Honeypot anti-bot : champ INVISIBLE pour un humain (masqué en CSS
    # dans le formulaire public). Un bot qui remplit tous les champs le
    # remplit aussi → classé spam. Nom volontairement appétissant.
    website: Optional[str] = Form(None),
    photos: List[UploadFile] = File(default=[]),
) -> ContactRequestPublicAck:
    if not gdpr_consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consent is required to submit a contact request.",
        )

    try:
        # Normalisation : padding pour atteindre le min_length=10
        # de Pydantic dans le cas des créations manuelles depuis
        # le CRM (où on accepte un message court ou vide). Le
        # placeholder reste explicite pour qu'on sache que le
        # message a été enrichi côté serveur.
        msg_clean = (message or "").strip()
        if len(msg_clean) < 10:
            msg_clean = (
                f"{msg_clean} — (note courte, source: {source or 'inconnu'})"
                if msg_clean
                else "(création manuelle, sans note)"
            )
        data = ContactRequestCreate(
            name=name,
            email=email,
            phone=phone or None,
            address=address or None,
            project_type=ProjectType(project_type) if project_type else ProjectType.AUTRE,
            budget_range=budget_range or None,
            message=msg_clean,
            locale=locale if locale in ("fr", "en") else "fr",
            source=source or None,
            gdpr_consent=gdpr_consent,
            marketing_consent=marketing_consent,
        )
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )

    ip_address = _client_ip(request)
    user_agent = request.headers.get("user-agent")

    service = ContactRequestService(db)
    try:
        record = await service.submit_public(
            data=data, ip_address=ip_address, user_agent=user_agent
        )
    except ValueError as exc:
        if str(exc) == "rate_limited":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many submissions. Please try again later.",
            )
        raise

    reference = ContactRequestService.build_reference(record)

    # Détection de spam (bots SEO : nom aléatoire, Gmail « à points »,
    # liens, honeypot rempli). La demande est CONSERVÉE mais classée
    # « spam » (révisable dans le CRM), et TOUS les effets de bord sont
    # sautés : pas de notification aux managers, pas de cadence de suivi,
    # pas d'accusé de réception, et surtout PAS d'appel sortant
    # automatique de Léa vers un numéro bidon. Le bot reçoit l'accusé
    # normal — aucun indice qu'il a été détecté.
    from app.services.contact_spam import looks_like_spam

    spam_reason = looks_like_spam(
        name=record.name or "",
        email=record.email or "",
        message=record.message or "",
        honeypot=website,
    )
    if spam_reason:
        import logging

        record.status = ContactRequestStatus.SPAM.value
        await db.flush()
        logging.getLogger(__name__).info(
            "Contact %s classé spam (%s) — effets de bord sautés",
            record.id,
            spam_reason,
        )
        return ContactRequestPublicAck(reference=reference)

    photo_payloads: list[tuple[str, bytes, str]] = []
    if photos:
        for up in photos[:MAX_PHOTOS]:
            ct = (up.content_type or "").lower()
            if ct not in ALLOWED_CONTENT_TYPES:
                continue
            content = await up.read(MAX_PHOTO_BYTES + 1)
            if not content or len(content) > MAX_PHOTO_BYTES:
                continue
            photo_payloads.append((up.filename or "photo.jpg", content, ct))

    # Persist the validated photos alongside the contact request so
    # the admin zone can display them in the prospect's Documents tab
    # (independent of the Monday.com push, which is best-effort).
    for filename, content, ct in photo_payloads:
        db.add(
            ContactRequestPhoto(
                contact_request_id=record.id,
                image=content,
                content_type=ct,
                filename=filename,
            )
        )
    if photo_payloads:
        await db.flush()

    # Fan-out a notification to every manager+ so they see the new
    # prospect in the bell immediately.
    try:
        from app.services.notifications import notify_role

        await notify_role(
            db,
            min_role="manager",
            kind="prospect.created",
            title=f"Nouveau prospect : {record.name}",
            body=(
                (record.message or "").strip()[:200]
                or f"{record.email} — {record.project_type}"
            ),
            href=f"/app/crm/{record.id}",
        )
    except Exception:
        # Never fail the public form on a notification error.
        pass

    # Démarre la cadence de suivi commercial : « Premier appel » dans 24 h.
    try:
        from app.services.follow_up import schedule_first_followup

        await schedule_first_followup(
            db, subject_type="prospect", subject_id=record.id
        )
    except Exception:
        pass

    # Accusé de réception au prospect : « demande reçue, on vous rappelle
    # bientôt ». Best-effort — n'interrompt jamais la soumission.
    try:
        from app.services.contact_request_mail import (
            send_contact_acknowledgment,
        )

        await send_contact_acknowledgment(record)
    except Exception:
        pass

    # AI outbound : Léa rappelle automatiquement le lead dans 60 sec
    # pour qualifier et proposer un RDV. Best-effort — la création du
    # ContactRequest n'échoue jamais à cause de ça.
    try:
        if record.phone:
            from app.integrations.voice.lead_outbound import (
                start_lead_qualification_call,
            )
            import asyncio as _asyncio

            _asyncio.create_task(
                start_lead_qualification_call(
                    contact_request_id=record.id, delay_sec=60
                )
            )
    except Exception:
        pass

    return ContactRequestPublicAck(reference=reference)


@router.get(
    "",
    response_model=List[ContactRequestRead],
    summary="List contact requests (staff)",
)
async def list_contact_requests(
    db: DBSession,
    current_user: RequireManager,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=1000),
    status_filter: Optional[ContactRequestStatus] = Query(default=None, alias="status"),
    mine: bool = Query(
        default=False,
        description="Si true, ne retourne que les leads assignés au user "
        "courant (raccourci pour assigned_to_user_id=<me>).",
    ),
    assigned_to_user_id: Optional[int] = Query(default=None),
    unassigned: bool = Query(default=False),
) -> List[ContactRequestRead]:
    service = ContactRequestService(db)
    target_uid = (
        current_user.id
        if mine
        else assigned_to_user_id
    )
    records = await service.list(
        skip=skip,
        limit=limit,
        status=status_filter.value if status_filter else None,
        assigned_to_user_id=target_uid,
        unassigned=unassigned and target_uid is None,
    )
    return [ContactRequestRead.model_validate(r) for r in records]


@router.get(
    "/{request_id}",
    response_model=ContactRequestRead,
    summary="Get a contact request by ID (staff)",
)
async def get_contact_request(
    request_id: int,
    db: DBSession,
    current_user: CurrentUser,
) -> ContactRequestRead:
    service = ContactRequestService(db)
    record = await service.get(request_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return ContactRequestRead.model_validate(record)


@router.patch(
    "/{request_id}",
    response_model=ContactRequestRead,
    summary="Update a contact request (staff)",
)
async def update_contact_request(
    request_id: int,
    data: ContactRequestUpdate,
    db: DBSession,
    current_user: CurrentUser,
) -> ContactRequestRead:
    service = ContactRequestService(db)
    record = await service.update(request_id, data)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return ContactRequestRead.model_validate(record)


@router.delete(
    "/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a contact request (staff)",
)
async def delete_contact_request(
    request_id: int,
    db: DBSession,
    current_user: CurrentUser,
) -> None:
    service = ContactRequestService(db)
    deleted = await service.delete(request_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    if request.client:
        return request.client.host
    return None


# ---------- Photos attached to a prospect contact request ----------


class ContactPhotoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_request_id: int
    content_type: str
    filename: Optional[str]
    created_at: datetime


@router.post(
    "/{request_id}/photos",
    response_model=ContactPhotoRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a photo to a contact request (staff)",
)
async def upload_contact_photo(
    request_id: int,
    db: DBSession,
    _: CurrentUser,
    file: UploadFile = File(...),
) -> ContactPhotoRead:
    ct = (file.content_type or "").lower()
    if ct not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Format image non supporté (JPG, PNG, WEBP, HEIC).",
        )
    blob = await file.read(MAX_PHOTO_BYTES + 1)
    if not blob:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Fichier vide."
        )
    if len(blob) > MAX_PHOTO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Fichier trop gros (>{MAX_PHOTO_BYTES // (1024 * 1024)} Mo).",
        )
    service = ContactRequestService(db)
    if await service.get(request_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Prospect introuvable."
        )
    photo = ContactRequestPhoto(
        contact_request_id=request_id,
        image=blob,
        content_type=ct,
        filename=file.filename,
    )
    db.add(photo)
    await db.flush()
    await db.refresh(photo)
    return ContactPhotoRead.model_validate(photo)


@router.get(
    "/{request_id}/photos",
    response_model=List[ContactPhotoRead],
    summary="List photos attached to a contact request (staff)",
)
async def list_contact_photos(
    request_id: int, db: DBSession, _: CurrentUser
) -> List[ContactPhotoRead]:
    rows = (
        await db.execute(
            select(ContactRequestPhoto)
            .where(ContactRequestPhoto.contact_request_id == request_id)
            .order_by(ContactRequestPhoto.created_at.asc())
        )
    ).scalars().all()
    return [ContactPhotoRead.model_validate(r) for r in rows]


@router.get(
    "/{request_id}/photos/{photo_id}/image",
    summary="Stream the photo bytes inline (staff)",
)
async def stream_contact_photo(
    request_id: int, photo_id: int, db: DBSession, _: CurrentUser
) -> Response:
    p = (
        await db.execute(
            select(ContactRequestPhoto).where(
                ContactRequestPhoto.id == photo_id,
                ContactRequestPhoto.contact_request_id == request_id,
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo introuvable."
        )
    await db.refresh(p, attribute_names=["image"])
    if not p.image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo vide."
        )
    return Response(
        content=bytes(p.image),
        media_type=p.content_type,
        headers={
            "Content-Disposition": (
                f'inline; filename="{p.filename or f"photo-{p.id}"}"'
            )
        },
    )


@router.delete(
    "/{request_id}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a photo from a contact request (staff)",
)
async def delete_contact_photo(
    request_id: int, photo_id: int, db: DBSession, _: CurrentUser
) -> None:
    p = (
        await db.execute(
            select(ContactRequestPhoto).where(
                ContactRequestPhoto.id == photo_id,
                ContactRequestPhoto.contact_request_id == request_id,
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo introuvable."
        )
    await db.delete(p)
    await db.flush()


# ─── Validation publique (token) — page de validation post-appel ───
# Quand la secrétaire IA collecte les besoins en construction au
# téléphone, on génère un `validation_token` pour le ContactRequest
# et on envoie un courriel au client avec le lien :
#   https://horizon.../valider-demande/{token}
# La page publique (sans auth) appelle ces endpoints :
#   GET  /api/v1/contact/by-token/{token}                  -> infos
#   PATCH /api/v1/contact/by-token/{token}                 -> édite infos
#   POST  /api/v1/contact/by-token/{token}/photos          -> upload
#   GET   /api/v1/contact/by-token/{token}/photos          -> liste
#   GET   /api/v1/contact/by-token/{token}/photos/{id}/image -> stream
#   DELETE /api/v1/contact/by-token/{token}/photos/{id}    -> supprime
#   POST  /api/v1/contact/by-token/{token}/confirm         -> validé
#
# Aucune authentification : le token est secret. La portée d'écriture
# est strictement limitée aux champs édités par le client (jamais
# status, assigned_to_user_id, internal_notes, intake_data brut).
from app.models.contact_request import ContactRequest


class ContactPublicRead(BaseModel):
    """Vue publique d'un ContactRequest — utilisée par la page
    de validation. On expose UNIQUEMENT les champs visibles au
    client, jamais les notes internes ni l'assignation CRM."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    phone: Optional[str]
    address: Optional[str]
    project_type: str
    budget_range: Optional[str]
    message: str
    locale: str
    intake_data: Optional[str]
    validated_at: Optional[datetime]


class ContactPublicUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    project_type: Optional[str] = None
    budget_range: Optional[str] = None
    message: Optional[str] = None


async def _load_by_token(db, token: str) -> ContactRequest:
    if not token or len(token) < 10:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lien invalide.")
    cr = (
        await db.execute(
            select(ContactRequest).where(
                ContactRequest.validation_token == token
            )
        )
    ).scalar_one_or_none()
    if cr is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Lien introuvable ou expiré.",
        )
    return cr


@router.get(
    "/by-token/{token}",
    response_model=ContactPublicRead,
    summary="(Public) Récupère un ContactRequest par son token de validation",
)
async def get_by_token(token: str, db: DBSession) -> ContactPublicRead:
    cr = await _load_by_token(db, token)
    return ContactPublicRead.model_validate(cr)


@router.patch(
    "/by-token/{token}",
    response_model=ContactPublicRead,
    summary="(Public) Édite les infos client d'un ContactRequest via son token",
)
async def patch_by_token(
    token: str, payload: ContactPublicUpdate, db: DBSession
) -> ContactPublicRead:
    cr = await _load_by_token(db, token)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is not None and isinstance(v, str):
            v = v.strip() or None
        setattr(cr, k, v)
    await db.flush()
    return ContactPublicRead.model_validate(cr)


@router.post(
    "/by-token/{token}/photos",
    response_model=ContactPhotoRead,
    status_code=status.HTTP_201_CREATED,
    summary="(Public) Upload une photo via le token",
)
async def upload_photo_by_token(
    token: str, db: DBSession, file: UploadFile = File(...)
) -> ContactPhotoRead:
    cr = await _load_by_token(db, token)
    ct = (file.content_type or "").lower()
    if ct not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Format image non supporté (JPG, PNG, WEBP, HEIC).",
        )
    # Cap dur — évite qu'un visiteur uploade des Go via le lien public.
    existing = (
        await db.execute(
            select(ContactRequestPhoto).where(
                ContactRequestPhoto.contact_request_id == cr.id
            )
        )
    ).scalars().all()
    if len(existing) >= MAX_PHOTOS * 4:  # public a un peu plus de marge
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Limite atteinte : max {MAX_PHOTOS * 4} photos par demande.",
        )
    blob = await file.read(MAX_PHOTO_BYTES + 1)
    if not blob:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Fichier vide."
        )
    if len(blob) > MAX_PHOTO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Fichier trop gros (>{MAX_PHOTO_BYTES // (1024 * 1024)} Mo).",
        )
    photo = ContactRequestPhoto(
        contact_request_id=cr.id,
        image=blob,
        content_type=ct,
        filename=file.filename,
    )
    db.add(photo)
    await db.flush()
    await db.refresh(photo)
    return ContactPhotoRead.model_validate(photo)


@router.get(
    "/by-token/{token}/photos",
    response_model=List[ContactPhotoRead],
    summary="(Public) Liste des photos déjà uploadées",
)
async def list_photos_by_token(
    token: str, db: DBSession
) -> List[ContactPhotoRead]:
    cr = await _load_by_token(db, token)
    rows = (
        await db.execute(
            select(ContactRequestPhoto)
            .where(ContactRequestPhoto.contact_request_id == cr.id)
            .order_by(ContactRequestPhoto.created_at.asc())
        )
    ).scalars().all()
    return [ContactPhotoRead.model_validate(r) for r in rows]


@router.get(
    "/by-token/{token}/photos/{photo_id}/image",
    summary="(Public) Affiche une photo via le token",
)
async def stream_photo_by_token(
    token: str, photo_id: int, db: DBSession
) -> Response:
    cr = await _load_by_token(db, token)
    p = (
        await db.execute(
            select(ContactRequestPhoto).where(
                ContactRequestPhoto.id == photo_id,
                ContactRequestPhoto.contact_request_id == cr.id,
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo introuvable."
        )
    await db.refresh(p, attribute_names=["image"])
    if not p.image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo vide."
        )
    return Response(
        content=bytes(p.image),
        media_type=p.content_type,
        headers={
            "Content-Disposition": (
                f'inline; filename="{p.filename or f"photo-{p.id}"}"'
            )
        },
    )


@router.delete(
    "/by-token/{token}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="(Public) Supprime une photo via le token",
)
async def delete_photo_by_token(
    token: str, photo_id: int, db: DBSession
) -> None:
    cr = await _load_by_token(db, token)
    p = (
        await db.execute(
            select(ContactRequestPhoto).where(
                ContactRequestPhoto.id == photo_id,
                ContactRequestPhoto.contact_request_id == cr.id,
            )
        )
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo introuvable."
        )
    await db.delete(p)
    await db.flush()


@router.post(
    "/by-token/{token}/confirm",
    response_model=ContactPublicRead,
    summary="(Public) Confirme la demande après relecture — verrouille l'édition côté client",
)
async def confirm_by_token(
    token: str, db: DBSession
) -> ContactPublicRead:
    cr = await _load_by_token(db, token)
    if cr.validated_at is None:
        cr.validated_at = datetime.utcnow()
    await db.flush()
    return ContactPublicRead.model_validate(cr)
