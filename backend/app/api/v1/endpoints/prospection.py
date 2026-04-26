"""Endpoints du module Prospection (drive-by lead capture).

Liste, création (multipart pour la photo), mise à jour, suppression,
ajout de photos supplémentaires, conversion vers ContactRequest /
Project.

Lookup propriétaire via rôle d'évaluation et REQ : Phase 2.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DBSession
from app.models.prospection_lead import (
    ProspectionLead,
    ProspectionLeadKind,
    ProspectionLeadStatus,
    ProspectionOwnerKind,
)
from app.models.prospection_lead_photo import ProspectionLeadPhoto

router = APIRouter(prefix="/prospection", tags=["prospection"])


# ------------------------------ Schemas ------------------------------


class LeadPhotoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    position: int
    content_type: str
    caption: Optional[str]
    created_at: datetime


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_by_user_id: Optional[int]
    created_at: datetime
    name: str
    kind: str
    address: Optional[str]
    city: Optional[str]
    postal_code: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    notes: Optional[str]
    status: str
    priority: int
    matricule: Optional[str]
    nb_logements: Optional[int]
    annee_construction: Optional[int]
    valeur_fonciere: Optional[float]
    superficie_terrain: Optional[float]
    owner_kind: str
    owner_name: Optional[str]
    owner_address: Optional[str]
    owner_email: Optional[str]
    owner_phone: Optional[str]
    owner_neq: Optional[str]
    last_contacted_at: Optional[datetime]
    contact_attempts_count: int
    assigned_to_user_id: Optional[int]
    converted_to_contact_request_id: Optional[int]
    converted_to_project_id: Optional[int]
    archived: bool
    photos_count: int = 0


class LeadUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    kind: Optional[str] = None
    address: Optional[str] = Field(default=None, max_length=500)
    city: Optional[str] = Field(default=None, max_length=120)
    postal_code: Optional[str] = Field(default=None, max_length=16)
    lat: Optional[float] = None
    lng: Optional[float] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    matricule: Optional[str] = None
    nb_logements: Optional[int] = None
    annee_construction: Optional[int] = None
    valeur_fonciere: Optional[float] = None
    superficie_terrain: Optional[float] = None
    owner_kind: Optional[str] = None
    owner_name: Optional[str] = None
    owner_address: Optional[str] = None
    owner_email: Optional[str] = None
    owner_phone: Optional[str] = None
    owner_neq: Optional[str] = None
    archived: Optional[bool] = None
    assigned_to_user_id: Optional[int] = None


_ALLOWED_PHOTO_CONTENT = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}
_MAX_PHOTO_BYTES = 15 * 1024 * 1024  # 15 Mo


# ------------------------------ Helpers ------------------------------


async def _photos_count_for(db, lead_id: int) -> int:
    res = await db.execute(
        select(ProspectionLeadPhoto.id).where(
            ProspectionLeadPhoto.lead_id == lead_id
        )
    )
    return len(res.all())


def _serialize(lead: ProspectionLead, photos_count: int) -> LeadRead:
    obj = LeadRead.model_validate(lead)
    obj.photos_count = photos_count
    return obj


# ------------------------------ Endpoints ------------------------------


@router.get("", response_model=List[LeadRead])
async def list_leads(
    db: DBSession,
    _: CurrentUser,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    kind: Optional[str] = None,
    archived: bool = False,
    limit: int = 500,
) -> List[LeadRead]:
    stmt = select(ProspectionLead).where(ProspectionLead.archived == archived)
    if status_filter:
        stmt = stmt.where(ProspectionLead.status == status_filter)
    if kind:
        stmt = stmt.where(ProspectionLead.kind == kind)
    stmt = stmt.order_by(ProspectionLead.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    # Compteur de photos par lead — une seule query groupée
    if not rows:
        return []
    ids = [r.id for r in rows]
    photo_rows = (
        await db.execute(
            select(ProspectionLeadPhoto.lead_id, ProspectionLeadPhoto.id).where(
                ProspectionLeadPhoto.lead_id.in_(ids)
            )
        )
    ).all()
    counts: dict[int, int] = {}
    for lead_id, _photo_id in photo_rows:
        counts[lead_id] = counts.get(lead_id, 0) + 1
    return [_serialize(r, counts.get(r.id, 0)) for r in rows]


@router.get("/{lead_id}", response_model=LeadRead)
async def get_lead(
    lead_id: int, db: DBSession, _: CurrentUser
) -> LeadRead:
    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")
    photos_count = await _photos_count_for(db, lead_id)
    return _serialize(lead, photos_count)


@router.post(
    "",
    response_model=LeadRead,
    status_code=status.HTTP_201_CREATED,
    summary="Quick-add depuis le mode drive-by (multipart, photo + GPS)",
)
async def create_lead(
    db: DBSession,
    user: CurrentUser,
    name: str = Form(...),
    kind: str = Form(default=ProspectionLeadKind.MULTILOGEMENT.value),
    address: Optional[str] = Form(default=None),
    city: Optional[str] = Form(default=None),
    postal_code: Optional[str] = Form(default=None),
    lat: Optional[float] = Form(default=None),
    lng: Optional[float] = Form(default=None),
    notes: Optional[str] = Form(default=None),
    priority: int = Form(default=3),
    photo: Optional[UploadFile] = File(default=None),
) -> LeadRead:
    final_address = (address or "").strip() or None
    final_city = (city or "").strip() or None
    final_postal = (postal_code or "").strip() or None

    # Reverse-geocoding : si on a des coordonnées GPS mais pas d'adresse
    # encore saisie, on demande à Nominatim (OpenStreetMap, gratuit) de
    # résoudre lat/lng → adresse + ville + code postal.
    if lat is not None and lng is not None and not final_address:
        from app.integrations.nominatim import reverse_geocode

        geo = await reverse_geocode(lat, lng)
        if geo:
            final_address = final_address or geo.get("address")
            final_city = final_city or geo.get("city")
            final_postal = final_postal or geo.get("postal_code")

    lead = ProspectionLead(
        created_by_user_id=user.id,
        name=name.strip(),
        kind=kind,
        address=final_address,
        city=final_city,
        postal_code=final_postal,
        lat=lat,
        lng=lng,
        notes=(notes or "").strip() or None,
        priority=max(1, min(5, priority)),
        status=ProspectionLeadStatus.A_VISITER.value,
        owner_kind=ProspectionOwnerKind.INCONNU.value,
    )
    db.add(lead)
    await db.flush()

    photos_count = 0
    if photo is not None and photo.filename:
        ct = (photo.content_type or "").lower()
        if ct not in _ALLOWED_PHOTO_CONTENT:
            raise HTTPException(
                415,
                "Format photo non supporté (JPG/PNG/WEBP/HEIC).",
            )
        blob = await photo.read()
        if not blob:
            raise HTTPException(400, "Photo vide.")
        if len(blob) > _MAX_PHOTO_BYTES:
            raise HTTPException(413, "Photo trop volumineuse (max 15 Mo).")
        ph = ProspectionLeadPhoto(
            lead_id=lead.id,
            position=0,
            content_type=ct,
            content=blob,
        )
        db.add(ph)
        await db.flush()
        photos_count = 1

    await db.refresh(lead)
    return _serialize(lead, photos_count)


@router.patch("/{lead_id}", response_model=LeadRead)
async def update_lead(
    lead_id: int,
    data: LeadUpdate,
    db: DBSession,
    _: CurrentUser,
) -> LeadRead:
    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")
    update = data.model_dump(exclude_unset=True)
    for k, v in update.items():
        setattr(lead, k, v)
    await db.flush()
    await db.refresh(lead)
    photos_count = await _photos_count_for(db, lead_id)
    return _serialize(lead, photos_count)


@router.post(
    "/{lead_id}/resolve-address",
    response_model=LeadRead,
    summary="Re-résout l'adresse du lead via Nominatim (lat/lng → adresse).",
)
async def resolve_address(
    lead_id: int, db: DBSession, _: CurrentUser
) -> LeadRead:
    """Pour les leads créés en drive-by qui n'avaient pas encore une
    adresse résolue, ou pour rafraîchir une adresse qui semble fausse.
    Écrase address/city/postal_code avec ce que retourne OSM."""
    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")
    if lead.lat is None or lead.lng is None:
        raise HTTPException(
            400, "Pas de coordonnées GPS sur ce lead — impossible de résoudre."
        )
    from app.integrations.nominatim import reverse_geocode

    geo = await reverse_geocode(float(lead.lat), float(lead.lng))
    if geo is None:
        raise HTTPException(
            502, "Nominatim n'a rien retourné pour ces coordonnées."
        )
    if geo.get("address"):
        lead.address = geo["address"]
    if geo.get("city"):
        lead.city = geo["city"]
    if geo.get("postal_code"):
        lead.postal_code = geo["postal_code"]
    await db.flush()
    await db.refresh(lead)
    photos_count = await _photos_count_for(db, lead_id)
    return _serialize(lead, photos_count)


class OwnerEnrichmentResult(BaseModel):
    """Résultat agrégé d'un lookup propriétaire combinant rôle
    d'évaluation Montréal + corporations REQ."""

    lead: LeadRead
    # Ce qui a été appliqué automatiquement sur le lead
    applied: dict
    # Corporations dont l'adresse de domicile correspond à l'adresse
    # du lead (potentiels propriétaires si la propriété est à une cie).
    req_candidates: list[dict] = []
    notes: list[str] = []


@router.post(
    "/{lead_id}/enrich-owner",
    response_model=OwnerEnrichmentResult,
    summary="Enrichit le lead avec le rôle d'évaluation municipal "
    "(Montréal) et les corporations REQ correspondantes.",
)
async def enrich_owner(
    lead_id: int, db: DBSession, _: CurrentUser
) -> OwnerEnrichmentResult:
    """Pipeline :
    1. Lookup dans `mtl_property_units` à partir de l'adresse → matricule,
       nb_logements, année, superficies. Écrit ces champs sur le lead
       seulement s'ils sont vides (ne pas écraser une saisie manuelle).
    2. Lookup dans `req_companies` par adresse → liste de candidats
       corporations dont le siège est à cette adresse. On retourne la
       liste, l'utilisateur choisit (un clic remplit owner_*).
    """
    from app.integrations.req.companies import (
        lookup_by_address as req_lookup_by_address,
    )
    from app.integrations.roles_evaluation.montreal import (
        lookup_by_address as mtl_lookup_by_address,
    )

    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")
    if not (lead.address or "").strip():
        raise HTTPException(
            400, "Le lead n'a pas d'adresse — résolvez l'adresse d'abord."
        )

    applied: dict = {}
    notes: list[str] = []

    # 1. Rôle Montréal — uniquement si la ville matche (sinon ça ne sert
    #    à rien, voire ça remplit avec les données d'une homonymie).
    city_norm = (lead.city or "").strip().lower()
    if not city_norm or "montr" in city_norm:
        mtl = await mtl_lookup_by_address(db, lead.address)
        if mtl is None:
            notes.append(
                "Aucun match dans le rôle d'évaluation de Montréal pour "
                "cette adresse. Vérifie l'orthographe ou la ville."
            )
        else:
            for field in (
                "matricule",
                "nb_logements",
                "annee_construction",
                "superficie_terrain",
            ):
                current = getattr(lead, field)
                new_val = mtl.get(field)
                if new_val is not None and (current is None or current == ""):
                    setattr(lead, field, new_val)
                    applied[field] = new_val
            if mtl.get("libelle_utilisation"):
                notes.append(
                    f"Utilisation : {mtl['libelle_utilisation']}"
                )
    else:
        notes.append(
            "Le rôle Montréal n'est pas applicable hors Montréal "
            "(ville détectée : "
            f"{lead.city or 'inconnue'}). À venir : Longueuil, Brossard."
        )

    # 2. REQ — candidats corporations à cette adresse
    req_candidates: list[dict] = []
    req_rows = await req_lookup_by_address(db, lead.address, lead.city)
    for c in req_rows:
        req_candidates.append(
            {
                "neq": c.neq,
                "nom": c.nom,
                "statut": c.statut,
                "forme_juridique": c.forme_juridique,
                "adresse": c.adresse,
                "ville": c.ville,
                "code_postal": c.code_postal,
            }
        )
    if not req_candidates:
        notes.append(
            "Aucune corporation REQ trouvée à cette adresse "
            "(soit propriétaire particulier, soit ZIP REQ pas encore "
            "importé via /admin/data/req/import)."
        )

    if applied:
        await db.flush()
        await db.refresh(lead)
    photos_count = await _photos_count_for(db, lead_id)
    return OwnerEnrichmentResult(
        lead=_serialize(lead, photos_count),
        applied=applied,
        req_candidates=req_candidates,
        notes=notes,
    )


@router.delete(
    "/{lead_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_lead(
    lead_id: int, db: DBSession, _: CurrentUser
) -> None:
    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")
    await db.delete(lead)
    await db.flush()


# ------------------------------ Photos ------------------------------


@router.get("/{lead_id}/photos", response_model=List[LeadPhotoRead])
async def list_photos(
    lead_id: int, db: DBSession, _: CurrentUser
) -> List[LeadPhotoRead]:
    rows = (
        await db.execute(
            select(ProspectionLeadPhoto)
            .where(ProspectionLeadPhoto.lead_id == lead_id)
            .order_by(
                ProspectionLeadPhoto.position.asc(),
                ProspectionLeadPhoto.id.asc(),
            )
        )
    ).scalars().all()
    return [LeadPhotoRead.model_validate(p) for p in rows]


@router.post(
    "/{lead_id}/photos",
    response_model=LeadPhotoRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_photo(
    lead_id: int,
    db: DBSession,
    _: CurrentUser,
    photo: UploadFile = File(...),
    caption: Optional[str] = Form(default=None),
) -> LeadPhotoRead:
    lead = (
        await db.execute(
            select(ProspectionLead.id).where(
                ProspectionLead.id == lead_id
            )
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")
    ct = (photo.content_type or "").lower()
    if ct not in _ALLOWED_PHOTO_CONTENT:
        raise HTTPException(
            415, "Format non supporté (JPG/PNG/WEBP/HEIC)."
        )
    blob = await photo.read()
    if not blob:
        raise HTTPException(400, "Photo vide.")
    if len(blob) > _MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo trop volumineuse (max 15 Mo).")

    # Position = max existant + 1
    last = (
        await db.execute(
            select(ProspectionLeadPhoto.position)
            .where(ProspectionLeadPhoto.lead_id == lead_id)
            .order_by(ProspectionLeadPhoto.position.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    pos = (last or 0) + 1

    ph = ProspectionLeadPhoto(
        lead_id=lead_id,
        position=pos,
        content_type=ct,
        content=blob,
        caption=(caption or "").strip() or None,
    )
    db.add(ph)
    await db.flush()
    await db.refresh(ph)
    return LeadPhotoRead.model_validate(ph)


@router.get("/{lead_id}/photos/{photo_id}/content")
async def get_photo_content(
    lead_id: int, photo_id: int, db: DBSession, _: CurrentUser
) -> Response:
    ph = (
        await db.execute(
            select(ProspectionLeadPhoto).where(
                ProspectionLeadPhoto.id == photo_id,
                ProspectionLeadPhoto.lead_id == lead_id,
            )
        )
    ).scalar_one_or_none()
    if ph is None:
        raise HTTPException(404, "Photo introuvable")
    await db.refresh(ph, attribute_names=["content"])
    return Response(
        content=bytes(ph.content),
        media_type=ph.content_type,
        headers={
            "Cache-Control": "private, max-age=86400",
        },
    )


@router.delete(
    "/{lead_id}/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_photo(
    lead_id: int, photo_id: int, db: DBSession, _: CurrentUser
) -> None:
    res = await db.execute(
        delete(ProspectionLeadPhoto).where(
            ProspectionLeadPhoto.id == photo_id,
            ProspectionLeadPhoto.lead_id == lead_id,
        )
    )
    if (res.rowcount or 0) == 0:
        raise HTTPException(404, "Photo introuvable")
    await db.flush()
