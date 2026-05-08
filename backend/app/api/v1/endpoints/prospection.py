"""Endpoints du module Prospection (drive-by lead capture).

Liste, création (multipart pour la photo), mise à jour, suppression,
ajout de photos supplémentaires, conversion vers ContactRequest /
Project.

Lookup propriétaire via rôle d'évaluation et REQ : Phase 2.
"""

import logging
from datetime import date as DateT, datetime, timezone
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

from app.api.deps import CurrentAdmin, CurrentUser, DBSession
from app.models.prospection_lead import (
    ProspectionLead,
    ProspectionLeadKind,
    ProspectionLeadStatus,
    ProspectionOwnerKind,
)
from app.models.prospection_lead_photo import ProspectionLeadPhoto
from app.services.prospection_scoring import apply_score, parse_tags


log = logging.getLogger(__name__)

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
    score: int = 0
    tags: List[str] = []
    photos_count: int = 0
    # Données financières (saisie manuelle)
    purchase_price: Optional[float] = None
    purchase_date: Optional[DateT] = None
    mortgage_balance: Optional[float] = None
    tax_delinquent: bool = False
    tax_year_paid: Optional[int] = None
    tax_amount: Optional[float] = None
    mailing_address: Optional[str] = None
    # Computed : valeur - hypothèque (si les deux sont set)
    estimated_equity: Optional[float] = None
    estimated_equity_pct: Optional[float] = None
    # Nombre d'autres leads avec le même proprio (NEQ ou nom)
    multi_properties_count: int = 0
    # Buy-flow : stratégie + montants offre/cession
    deal_strategy: str = "undecided"
    offer_amount: Optional[float] = None
    assignment_price: Optional[float] = None
    # Profit estimé en cas de flip (assignment - offer)
    estimated_flip_profit: Optional[float] = None
    # URL du dossier Google Drive du lead.
    drive_folder_url: Optional[str] = None


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
    # Données financières
    purchase_price: Optional[float] = Field(default=None, ge=0)
    purchase_date: Optional[DateT] = None
    mortgage_balance: Optional[float] = Field(default=None, ge=0)
    tax_delinquent: Optional[bool] = None
    tax_year_paid: Optional[int] = Field(default=None, ge=1900, le=2100)
    tax_amount: Optional[float] = Field(default=None, ge=0)
    mailing_address: Optional[str] = Field(default=None, max_length=500)
    # Buy-flow
    deal_strategy: Optional[str] = Field(
        default=None, pattern="^(undecided|keep|flip)$"
    )
    offer_amount: Optional[float] = Field(default=None, ge=0)
    assignment_price: Optional[float] = Field(default=None, ge=0)
    # Drive : URL du dossier Google Drive du lead.
    drive_folder_url: Optional[str] = Field(default=None, max_length=1024)


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


def _safe_attr(obj, name, default=None):
    """getattr() qui tolère une colonne qui n'existe pas encore dans
    la DB (cas de la 1ère requête après deploy, avant que la migration
    additive ait tourné). Retourne `default` si SQLAlchemy lève."""
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _serialize(
    lead: ProspectionLead,
    photos_count: int,
    multi_properties_count: int = 0,
) -> LeadRead:
    # Construction explicite du dict — résiste à des colonnes
    # nouvellement ajoutées qui n'existent pas encore en prod (le
    # backend tourne avec le code récent mais la migration additive
    # n'a peut-être pas encore exécuté).
    data = {
        "id": _safe_attr(lead, "id"),
        "created_by_user_id": _safe_attr(lead, "created_by_user_id"),
        "created_at": _safe_attr(lead, "created_at"),
        "name": _safe_attr(lead, "name") or "",
        "kind": _safe_attr(lead, "kind") or "multilogement",
        "address": _safe_attr(lead, "address"),
        "city": _safe_attr(lead, "city"),
        "postal_code": _safe_attr(lead, "postal_code"),
        "lat": _safe_attr(lead, "lat"),
        "lng": _safe_attr(lead, "lng"),
        "notes": _safe_attr(lead, "notes"),
        "status": _safe_attr(lead, "status") or "a_visiter",
        "priority": _safe_attr(lead, "priority", 3),
        "matricule": _safe_attr(lead, "matricule"),
        "nb_logements": _safe_attr(lead, "nb_logements"),
        "annee_construction": _safe_attr(lead, "annee_construction"),
        "valeur_fonciere": (
            float(_safe_attr(lead, "valeur_fonciere"))
            if _safe_attr(lead, "valeur_fonciere") is not None
            else None
        ),
        "superficie_terrain": (
            float(_safe_attr(lead, "superficie_terrain"))
            if _safe_attr(lead, "superficie_terrain") is not None
            else None
        ),
        "owner_kind": _safe_attr(lead, "owner_kind") or "inconnu",
        "owner_name": _safe_attr(lead, "owner_name"),
        "owner_address": _safe_attr(lead, "owner_address"),
        "owner_email": _safe_attr(lead, "owner_email"),
        "owner_phone": _safe_attr(lead, "owner_phone"),
        "owner_neq": _safe_attr(lead, "owner_neq"),
        "last_contacted_at": _safe_attr(lead, "last_contacted_at"),
        "contact_attempts_count": _safe_attr(
            lead, "contact_attempts_count", 0
        ),
        "assigned_to_user_id": _safe_attr(lead, "assigned_to_user_id"),
        "converted_to_contact_request_id": _safe_attr(
            lead, "converted_to_contact_request_id"
        ),
        "converted_to_project_id": _safe_attr(
            lead, "converted_to_project_id"
        ),
        "archived": bool(_safe_attr(lead, "archived", False)),
        "score": _safe_attr(lead, "score", 0) or 0,
        "tags": parse_tags(_safe_attr(lead, "tags")),
        "photos_count": photos_count,
        # Champs Phase 3 — peuvent ne pas exister si la migration
        # additive n'a pas encore tourné en prod.
        "purchase_price": (
            float(_safe_attr(lead, "purchase_price"))
            if _safe_attr(lead, "purchase_price") is not None
            else None
        ),
        "purchase_date": _safe_attr(lead, "purchase_date"),
        "mortgage_balance": (
            float(_safe_attr(lead, "mortgage_balance"))
            if _safe_attr(lead, "mortgage_balance") is not None
            else None
        ),
        "tax_delinquent": bool(
            _safe_attr(lead, "tax_delinquent", False) or False
        ),
        "tax_year_paid": _safe_attr(lead, "tax_year_paid"),
        "tax_amount": (
            float(_safe_attr(lead, "tax_amount"))
            if _safe_attr(lead, "tax_amount") is not None
            else None
        ),
        "mailing_address": _safe_attr(lead, "mailing_address"),
        "drive_folder_url": _safe_attr(lead, "drive_folder_url"),
        "estimated_equity": None,
        "estimated_equity_pct": None,
        "multi_properties_count": multi_properties_count,
        # Buy-flow
        "deal_strategy": _safe_attr(lead, "deal_strategy", "undecided")
        or "undecided",
        "offer_amount": (
            float(_safe_attr(lead, "offer_amount"))
            if _safe_attr(lead, "offer_amount") is not None
            else None
        ),
        "assignment_price": (
            float(_safe_attr(lead, "assignment_price"))
            if _safe_attr(lead, "assignment_price") is not None
            else None
        ),
        "estimated_flip_profit": None,
    }

    # Equity computée
    if data["valeur_fonciere"] and data["mortgage_balance"] is not None:
        valeur = data["valeur_fonciere"]
        mortgage = data["mortgage_balance"]
        data["estimated_equity"] = valeur - mortgage
        if valeur > 0:
            data["estimated_equity_pct"] = round(
                (valeur - mortgage) / valeur * 100, 1
            )

    # Profit estimé du flip (si offre soumise + cession prévue)
    if data["offer_amount"] and data["assignment_price"]:
        data["estimated_flip_profit"] = (
            data["assignment_price"] - data["offer_amount"]
        )

    return LeadRead.model_validate(data)


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

    # Multi-properties : pour chaque lead, compte combien d'autres
    # leads non archivés partagent le même owner_neq (corp) ou
    # owner_name (particulier nommé). Pré-calculé en une passe.
    by_neq: dict[str, int] = {}
    by_name: dict[str, int] = {}
    for r in rows:
        if r.owner_neq:
            by_neq[r.owner_neq] = by_neq.get(r.owner_neq, 0) + 1
        elif r.owner_name:
            key = r.owner_name.strip().lower()
            if key:
                by_name[key] = by_name.get(key, 0) + 1
    multi: dict[int, int] = {}
    for r in rows:
        if r.owner_neq:
            multi[r.id] = max(0, by_neq.get(r.owner_neq, 1) - 1)
        elif r.owner_name:
            key = r.owner_name.strip().lower()
            multi[r.id] = max(0, by_name.get(key, 1) - 1)
        else:
            multi[r.id] = 0

    return [
        _serialize(r, counts.get(r.id, 0), multi.get(r.id, 0))
        for r in rows
    ]


class DashboardStats(BaseModel):
    """KPIs et séries temporelles agrégés pour la page dashboard
    Prospection. Tout vient d'une seule passe sur les leads non
    archivés — pas de query supplémentaire."""

    total_leads: int
    by_status: dict
    by_kind: dict
    avg_score: float
    high_score_count: int  # score >= 70
    converted_count: int
    conversion_rate: float  # converted / (converted + perdu + actif)
    leads_per_week: list[dict]  # [{"week": "2026-W17", "count": 5}, ...]
    score_distribution: list[dict]  # [{"bucket": "70-100", "count": 8}, ...]
    top_cities: list[dict]  # [{"city": "Montréal", "count": 42}, ...]


@router.get(
    "/dashboard/stats",
    response_model=DashboardStats,
    summary="KPIs agrégés du module Prospection (compteurs, "
    "distributions, séries temporelles).",
)
async def dashboard_stats(
    db: DBSession, _: CurrentUser
) -> DashboardStats:
    rows = (
        await db.execute(
            select(ProspectionLead).where(
                ProspectionLead.archived.is_(False)
            )
        )
    ).scalars().all()

    total = len(rows)
    by_status: dict = {}
    by_kind: dict = {}
    score_sum = 0
    high_score = 0
    converted = 0
    perdu = 0
    week_counts: dict = {}
    city_counts: dict = {}
    score_buckets = {
        "0-29": 0,
        "30-49": 0,
        "50-69": 0,
        "70-100": 0,
    }

    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
        s = r.score or 0
        score_sum += s
        if s >= 70:
            high_score += 1
            score_buckets["70-100"] += 1
        elif s >= 50:
            score_buckets["50-69"] += 1
        elif s >= 30:
            score_buckets["30-49"] += 1
        else:
            score_buckets["0-29"] += 1
        if r.status == "converti":
            converted += 1
        if r.status == "perdu":
            perdu += 1
        if r.created_at:
            iso_year, iso_week, _ = r.created_at.isocalendar()
            wk = f"{iso_year}-W{iso_week:02d}"
            week_counts[wk] = week_counts.get(wk, 0) + 1
        if r.city:
            city_counts[r.city] = city_counts.get(r.city, 0) + 1

    avg_score = (score_sum / total) if total else 0.0
    # Conversion rate = convertis / leads ayant atteint un état final
    # (converti ou perdu) — sinon dilution par les leads encore en
    # cours qui n'ont jamais eu la chance d'être convertis.
    final_count = converted + perdu
    conversion_rate = (converted / final_count) if final_count else 0.0

    # Séries triées
    leads_per_week = [
        {"week": k, "count": v}
        for k, v in sorted(week_counts.items())
    ][-26:]  # 6 derniers mois max

    score_distribution = [
        {"bucket": k, "count": v} for k, v in score_buckets.items()
    ]

    top_cities = sorted(
        ({"city": c, "count": n} for c, n in city_counts.items()),
        key=lambda x: x["count"],
        reverse=True,
    )[:8]

    return DashboardStats(
        total_leads=total,
        by_status=by_status,
        by_kind=by_kind,
        avg_score=round(avg_score, 1),
        high_score_count=high_score,
        converted_count=converted,
        conversion_rate=round(conversion_rate, 3),
        leads_per_week=leads_per_week,
        score_distribution=score_distribution,
        top_cities=top_cities,
    )


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
    name: Optional[str] = Form(default=None),
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
    final_name = (name or "").strip() or None

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

    # Auto-génère le nom depuis l'adresse si pas fourni — l'utilisateur
    # n'a plus à saisir un nom à la main. Format « 4520 Saint-Laurent ».
    if not final_name:
        if final_address:
            final_name = final_address[:80]
        elif lat is not None and lng is not None:
            final_name = f"Lead GPS {lat:.4f},{lng:.4f}"
        else:
            final_name = "Nouveau lead"

    lead = ProspectionLead(
        created_by_user_id=user.id,
        name=final_name,
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
    apply_score(lead)
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
    user: CurrentUser,
) -> LeadRead:
    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")
    update = data.model_dump(exclude_unset=True)
    # Détecte la transition vers HOT_LEAD AVANT le setattr pour
    # qu'on ait l'ancien statut. Permet de ne notifier qu'à
    # l'instant du drag, pas à chaque sauvegarde subséquente.
    previous_status = lead.status
    new_status = update.get("status")
    just_became_hot = (
        new_status == ProspectionLeadStatus.HOT_LEAD.value
        and previous_status != ProspectionLeadStatus.HOT_LEAD.value
    )
    for k, v in update.items():
        setattr(lead, k, v)
    apply_score(lead)
    await db.flush()
    if just_became_hot:
        # Notifie Philippe + Steven + Michael (ou les noms configurés
        # dans HOT_LEAD_ALERT_FIRSTNAMES) — fan-out par first_name.
        from app.services.hot_lead_alerts import notify_hot_lead_team

        try:
            await notify_hot_lead_team(
                db,
                lead=lead,
                triggered_by_user_id=getattr(user, "id", None),
            )
        except Exception:  # noqa: BLE001
            # On ne bloque pas l'update si la notif échoue.
            log.exception("notify_hot_lead_team failed for lead %s", lead_id)
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
                "telephone": c.telephone,
            }
        )
    if not req_candidates:
        notes.append(
            "Aucune corporation REQ trouvée à cette adresse "
            "(soit propriétaire particulier, soit ZIP REQ pas encore "
            "importé via /admin/data/req/import)."
        )

    if applied:
        apply_score(lead)
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
    lead_id: int,
    db: DBSession,
    _: CurrentUser,
    hard: bool = False,
) -> None:
    """Supprime un lead. Par défaut, soft-delete (set archived=true)
    pour pouvoir restaurer plus tard. Avec ?hard=true, hard-delete
    (DROP de la ligne) — réservé aux admins via /restore.

    Le soft-delete est plus sûr : si l'utilisateur clique trop vite
    sur la corbeille, on peut récupérer. Et les associations
    (FollowUp, etc.) restent intactes.
    """
    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")
    if hard:
        await db.delete(lead)
    else:
        lead.archived = True
    await db.flush()


# ------------------------ Phone search ------------------------


class PhoneFound(BaseModel):
    phone: str
    source: str   # "lespac", "kangalou"
    url: Optional[str] = None
    snippet: Optional[str] = None
    dncl_check_url: str   # URL pour vérifier sur la DNCL


class FindPhoneOut(BaseModel):
    results: List[PhoneFound]
    queries_tried: List[str]
    notes: List[str]


def _dncl_check_url(phone: str) -> str:
    """URL de la DNCL (Liste nationale des numéros de télécommunication
    exclus) pour vérifier qu'un numéro n'est pas inscrit avant un appel
    commercial. Obligation CRTC."""
    digits = re.sub(r"\D", "", phone)
    return f"https://lnnte-dncl.gc.ca/fr/Consumer/CheckRegistration?phone={digits}"


@router.post(
    "/{lead_id}/find-phone",
    response_model=FindPhoneOut,
    summary="Cherche le téléphone du propriétaire via les annonces "
    "publiques (LesPAC + Kangalou). Numéros NON stockés en base.",
)
async def find_phone(
    lead_id: int, db: DBSession, _: CurrentUser
) -> FindPhoneOut:
    """Pas de stockage du numéro en DB — chaque appel re-cherche en
    live. L'utilisateur doit vérifier la DNCL avant tout contact
    téléphonique commercial (obligation CRTC).
    """
    import re as _re
    from app.integrations.classifieds.phones import find_phones

    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")

    queries: List[str] = []
    if lead.address:
        if lead.city:
            queries.append(f"{lead.address} {lead.city}")
        else:
            queries.append(lead.address)
    if lead.owner_name and len(lead.owner_name.strip()) > 4:
        queries.append(lead.owner_name.strip())

    notes: List[str] = []
    if not queries:
        notes.append(
            "Pas d'adresse ni de nom de propriétaire — impossible "
            "de chercher."
        )
        return FindPhoneOut(
            results=[], queries_tried=[], notes=notes
        )

    raw = await find_phones(
        address=lead.address,
        owner_name=lead.owner_name,
        city=lead.city,
    )

    results: List[PhoneFound] = []
    for r in raw:
        results.append(
            PhoneFound(
                phone=r["phone"],
                source=r["source"],
                url=r.get("url"),
                snippet=r.get("snippet"),
                dncl_check_url=_dncl_check_url(r["phone"]),
            )
        )

    if not results:
        notes.append(
            "Aucun numéro trouvé dans les annonces récentes. Le "
            "proprio n'a peut-être pas publié sur LesPAC ou Kangalou, "
            "ou ses annonces ont expiré."
        )
    notes.append(
        "Avant tout appel commercial : vérifier sur la DNCL (bouton à "
        "côté du numéro). Mentionner la source de l'annonce au début "
        "de l'appel."
    )

    return FindPhoneOut(
        results=results, queries_tried=queries, notes=notes
    )


# ------------------------ Rental estimate ------------------------


# Mapping QC nomenclature → bedroom bracket SCHL.
# Les 5½ et 6½ utilisent le bracket "3+ BR" car la SCHL ne publie
# pas de granularité plus fine — on note explicitement à l'UI.
_QC_BEDROOM_TO_BRACKET = {
    "1.5": 0,   # studio / bachelor
    "2.5": 1,   # 1 chambre
    "3.5": 2,   # 2 chambres
    "4.5": 3,   # 3 chambres
    "5.5": 3,   # 3+ (estimation)
    "6.5": 3,   # 3+ (estimation)
}


class RentBracket(BaseModel):
    qc_label: str       # "1½", "2½", ...
    bedrooms: int       # 0..3 (bracket SCHL)
    avg_rent: Optional[float]
    is_estimate: bool   # True pour 5½ et 6½ (bracket 3+ utilisé)


class RentalEstimateOut(BaseModel):
    cma: Optional[str]
    zone: Optional[str]
    year: Optional[int]
    vacancy_rate: Optional[float]
    brackets: List[RentBracket]
    # Si le lead a nb_logements et un mix moyen (assumed: tout en 4½),
    # on calcule un revenu mensuel/annuel et un GRM.
    estimated_monthly_income: Optional[float]
    estimated_annual_income: Optional[float]
    grm: Optional[float]
    grm_rating: Optional[str]
    notes: List[str]


def _grm_rating(grm: float) -> str:
    """Classification GRM (Gross Rent Multiplier) selon les standards
    multi-logements — plus c'est bas, mieux c'est."""
    if grm < 7:
        return "excellent"
    if grm < 10:
        return "bon"
    if grm < 13:
        return "moyen"
    return "cher"


@router.get(
    "/{lead_id}/rental-estimate",
    response_model=RentalEstimateOut,
    summary="Loyers moyens SCHL pour la zone du lead + revenu locatif "
    "estimé + GRM (Gross Rent Multiplier).",
)
async def rental_estimate(
    lead_id: int, db: DBSession, _: CurrentUser
) -> RentalEstimateOut:
    from app.integrations.cmhc.rents import (
        best_match_for_lead,
        lookup_rents,
        normalize_zone,
    )
    from app.models.market_rent import MarketRent

    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")

    notes: List[str] = []

    # On essaie de matcher la ville du lead avec une zone SCHL connue.
    # Stratégie : (a) chercher une zone dont le nom contient lead.city ;
    # (b) sinon agrégat CMA "Montréal" si lead.city contient "montr*".
    cma: Optional[str] = None
    zone: Optional[str] = None

    if lead.city:
        # Toutes les zones distinctes (CMA, zone) en base
        rows = (
            await db.execute(
                select(MarketRent.cma, MarketRent.zone).distinct()
            )
        ).all()
        zones_in_db = [r[1] for r in rows if r[1]]
        match = best_match_for_lead(
            lead_city=lead.city, available_zones=zones_in_db
        )
        if match:
            zone = match
            # Trouve le CMA correspondant
            for c, z in rows:
                if z == match:
                    cma = c
                    break
        else:
            # Fallback : CMA dont le nom matche la ville (ex: "Montréal")
            city_norm = normalize_zone(lead.city)
            for c, _z in rows:
                if normalize_zone(c) in city_norm or city_norm in normalize_zone(
                    c
                ):
                    cma = c
                    break

    if not cma:
        notes.append(
            "Aucune zone SCHL ne correspond à cette ville. Importe le "
            "CSV SCHL via /prospection/sources puis réessaie."
        )
        return RentalEstimateOut(
            cma=None,
            zone=None,
            year=None,
            vacancy_rate=None,
            brackets=[],
            estimated_monthly_income=None,
            estimated_annual_income=None,
            grm=None,
            grm_rating=None,
            notes=notes,
        )

    schl_rows = await lookup_rents(db, cma=cma, zone=zone)
    by_bracket: Dict[int, MarketRent] = {r.bedrooms: r for r in schl_rows}
    year = schl_rows[0].year if schl_rows else None
    vacancy = (
        float(schl_rows[0].vacancy_rate)
        if schl_rows and schl_rows[0].vacancy_rate is not None
        else None
    )

    if not zone:
        notes.append(
            f"Pas de sous-zone SCHL pour cette ville — utilisation de "
            f"l'agrégat « {cma} »."
        )

    qc_brackets = [
        ("1½", "1.5"),
        ("2½", "2.5"),
        ("3½", "3.5"),
        ("4½", "4.5"),
        ("5½", "5.5"),
        ("6½", "6.5"),
    ]
    brackets_out: List[RentBracket] = []
    for label, key in qc_brackets:
        bracket = _QC_BEDROOM_TO_BRACKET[key]
        rent_row = by_bracket.get(bracket)
        rent = (
            float(rent_row.avg_rent)
            if rent_row and rent_row.avg_rent is not None
            else None
        )
        brackets_out.append(
            RentBracket(
                qc_label=label,
                bedrooms=bracket,
                avg_rent=rent,
                # 5½ et 6½ utilisent le bracket 3+ → c'est une estimation
                is_estimate=key in ("5.5", "6.5"),
            )
        )

    # Estimation revenu : approche conservatrice — on prend le bracket
    # 4½ (3 chambres) comme moyenne représentative du multi-logement
    # typique. Si pas dispo, on prend 3½ (2 chambres) en fallback.
    est_monthly = None
    if lead.nb_logements:
        ref_rent = (
            float(by_bracket[3].avg_rent)
            if 3 in by_bracket and by_bracket[3].avg_rent
            else float(by_bracket[2].avg_rent)
            if 2 in by_bracket and by_bracket[2].avg_rent
            else None
        )
        if ref_rent is not None:
            est_monthly = ref_rent * lead.nb_logements
            notes.append(
                f"Estimation basée sur "
                f"{'4½' if 3 in by_bracket and by_bracket[3].avg_rent else '3½'} "
                f"× {lead.nb_logements} logements."
            )

    est_annual = est_monthly * 12 if est_monthly is not None else None
    grm = None
    grm_label = None
    if est_annual and lead.valeur_fonciere and float(lead.valeur_fonciere) > 0:
        grm = float(lead.valeur_fonciere) / est_annual
        grm_label = _grm_rating(grm)

    return RentalEstimateOut(
        cma=cma,
        zone=zone,
        year=year,
        vacancy_rate=vacancy,
        brackets=brackets_out,
        estimated_monthly_income=est_monthly,
        estimated_annual_income=est_annual,
        grm=round(grm, 2) if grm else None,
        grm_rating=grm_label,
        notes=notes,
    )


# ------------------------ Score recompute ------------------------


@router.post(
    "/recompute-scores",
    summary="Recalcule le score+tags de tous les leads non archivés "
    "(à exécuter une fois après un changement de logique de scoring "
    "ou pour backfiller les leads créés avant l'introduction du score).",
)
async def recompute_scores(
    db: DBSession, _: CurrentUser
) -> dict:
    rows = (
        await db.execute(
            select(ProspectionLead).where(
                ProspectionLead.archived.is_(False)
            )
        )
    ).scalars().all()
    for lead in rows:
        apply_score(lead)
    await db.flush()
    return {"recomputed": len(rows)}


# ------------------------ Route optimization ------------------------


class RouteOptimizeIn(BaseModel):
    """Optimisation d'un itinéraire drive-by sur N leads géolocalisés.

    Si `start_lat`/`start_lng` sont fournis (typiquement la position
    GPS courante de l'utilisateur), l'itinéraire commence par ce point.
    """

    lead_ids: List[int] = Field(min_length=2, max_length=12)
    start_lat: Optional[float] = None
    start_lng: Optional[float] = None


class RouteOptimizeOut(BaseModel):
    ordered_lead_ids: List[int]
    total_distance_m: float
    total_duration_s: float
    google_maps_url: str


@router.post(
    "/route/optimize",
    response_model=RouteOptimizeOut,
    summary="Optimise l'ordre de visite de plusieurs leads via OSRM "
    "(public, gratuit) et retourne une URL Google Maps avec waypoints.",
)
async def optimize_route(
    payload: RouteOptimizeIn, db: DBSession, _: CurrentUser
) -> RouteOptimizeOut:
    import httpx

    rows = (
        await db.execute(
            select(ProspectionLead).where(
                ProspectionLead.id.in_(payload.lead_ids)
            )
        )
    ).scalars().all()
    by_id = {r.id: r for r in rows}
    geo_leads = [
        by_id[lid]
        for lid in payload.lead_ids
        if lid in by_id and by_id[lid].lat is not None
        and by_id[lid].lng is not None
    ]
    if len(geo_leads) < 2:
        raise HTTPException(
            400,
            "Au moins 2 leads géolocalisés sont requis pour optimiser "
            "un itinéraire.",
        )

    # OSRM "trip" attend les coordonnées en lng,lat séparées par ;.
    # On force le départ sur le premier point (start GPS si fourni,
    # sinon le premier lead) et on coupe l'aller-retour (roundtrip=false).
    coords: List[str] = []
    if payload.start_lat is not None and payload.start_lng is not None:
        coords.append(f"{payload.start_lng:.6f},{payload.start_lat:.6f}")
    for lead in geo_leads:
        coords.append(f"{float(lead.lng):.6f},{float(lead.lat):.6f}")

    url = (
        "https://router.project-osrm.org/trip/v1/driving/"
        + ";".join(coords)
        + "?source=first&roundtrip=false&overview=false"
    )

    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.get(
                url, headers={"User-Agent": "h2.0-Horizon/1.0"}
            )
            if r.status_code != 200:
                raise HTTPException(
                    502,
                    f"OSRM indisponible (HTTP {r.status_code}).",
                )
            data = r.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"OSRM erreur réseau : {exc}") from exc

    if data.get("code") != "Ok" or not data.get("trips"):
        raise HTTPException(
            502,
            f"OSRM réponse invalide : {data.get('code')}",
        )

    trip = data["trips"][0]
    waypoints = data.get("waypoints", [])
    # waypoint_index = position dans l'itinéraire optimisé (0-based).
    # Le 1er point peut être le start GPS — on l'exclut alors.
    has_start = (
        payload.start_lat is not None and payload.start_lng is not None
    )
    waypoint_to_lead: List[Optional[int]] = (
        [None] + [g.id for g in geo_leads]
        if has_start
        else [g.id for g in geo_leads]
    )

    indexed: List[tuple[int, int]] = []
    for orig_idx, wp in enumerate(waypoints):
        order_idx = wp.get("waypoint_index")
        if order_idx is None:
            continue
        lead_id = waypoint_to_lead[orig_idx]
        if lead_id is not None:
            indexed.append((order_idx, lead_id))
    indexed.sort()
    ordered_lead_ids = [lid for _, lid in indexed]

    # URL Google Maps avec waypoints en ordre optimisé.
    # Format : https://www.google.com/maps/dir/lat1,lng1/lat2,lng2/...
    parts: List[str] = []
    if has_start:
        parts.append(f"{payload.start_lat:.6f},{payload.start_lng:.6f}")
    by_id_geo = {g.id: g for g in geo_leads}
    for lid in ordered_lead_ids:
        g = by_id_geo[lid]
        parts.append(f"{float(g.lat):.6f},{float(g.lng):.6f}")
    google_maps_url = (
        "https://www.google.com/maps/dir/" + "/".join(parts)
    )

    return RouteOptimizeOut(
        ordered_lead_ids=ordered_lead_ids,
        total_distance_m=float(trip.get("distance", 0)),
        total_duration_s=float(trip.get("duration", 0)),
        google_maps_url=google_maps_url,
    )


# ------------------------ Convert to CRM ------------------------


class ConvertToContactIn(BaseModel):
    """Conversion d'un lead Prospection vers le CRM Construction.

    Crée un ContactRequest avec les champs pré-remplis depuis le lead
    (adresse + propriétaire si dispo), marque le lead comme converti
    et retourne l'id du nouveau ContactRequest pour que le frontend
    puisse rediriger vers /app/crm/{id}.
    """

    project_type: Optional[str] = None  # défaut multilogement
    message: Optional[str] = None
    override_email: Optional[str] = None
    override_phone: Optional[str] = None


class ConvertToContactOut(BaseModel):
    contact_request_id: int
    lead: LeadRead


@router.post(
    "/{lead_id}/convert-to-contact",
    response_model=ConvertToContactOut,
    summary="Convertit le lead en ContactRequest dans le CRM "
    "Construction. Marque le lead comme converti.",
)
async def convert_to_contact(
    lead_id: int,
    payload: ConvertToContactIn,
    db: DBSession,
    _: CurrentUser,
) -> ConvertToContactOut:
    from app.models.contact_request import (
        ContactRequest,
        ContactRequestStatus,
        ProjectType,
    )

    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")
    if lead.converted_to_contact_request_id:
        raise HTTPException(
            409,
            "Ce lead a déjà été converti vers le CRM "
            f"(ContactRequest #{lead.converted_to_contact_request_id}).",
        )

    # Le ContactRequest exige email + name ; on tolère un fallback
    # en placeholder à corriger côté CRM si pas d'info propriétaire.
    email = (
        (payload.override_email or "").strip()
        or (lead.owner_email or "").strip()
        or "a-completer@horizon-prospection.local"
    )
    phone = (
        (payload.override_phone or "").strip()
        or (lead.owner_phone or "").strip()
        or None
    )
    name = (lead.owner_name or "").strip() or lead.name

    full_address = ", ".join(
        x for x in (lead.address, lead.city, lead.postal_code) if x
    ) or None

    auto_message_parts: List[str] = [
        f"Lead Prospection #{lead.id} — {lead.name}.",
    ]
    if lead.nb_logements:
        auto_message_parts.append(f"{lead.nb_logements} logements")
    if lead.annee_construction:
        auto_message_parts.append(
            f"construit en {lead.annee_construction}"
        )
    if lead.matricule:
        auto_message_parts.append(f"matricule {lead.matricule}")
    if lead.notes:
        auto_message_parts.append(f"\nNotes terrain : {lead.notes}")
    auto_message = " · ".join(
        p for p in auto_message_parts if not p.startswith("\n")
    )
    if any(p.startswith("\n") for p in auto_message_parts):
        auto_message += next(
            p for p in auto_message_parts if p.startswith("\n")
        )

    message = (
        (payload.message or "").strip() or auto_message
    )

    project_type = (
        payload.project_type
        or ProjectType.MULTILOGEMENT.value
    )

    cr = ContactRequest(
        name=name,
        email=email,
        phone=phone,
        address=full_address,
        project_type=project_type,
        message=message,
        locale="fr",
        source=f"prospection-lead-{lead.id}",
        gdpr_consent=True,  # conversion interne, le consent a déjà
        # été obtenu lors de la capture initiale
        marketing_consent=False,
        status=ContactRequestStatus.NEW.value,
    )
    db.add(cr)
    await db.flush()

    lead.converted_to_contact_request_id = cr.id
    lead.status = "converti"
    apply_score(lead)
    await db.flush()
    await db.refresh(lead)

    photos_count = await _photos_count_for(db, lead_id)
    return ConvertToContactOut(
        contact_request_id=cr.id,
        lead=_serialize(lead, photos_count),
    )


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


# ------------------------ Transactions historiques ------------------------


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lead_id: int
    transaction_date: DateT
    amount: Optional[float]
    kind: str
    source: Optional[str]
    notes: Optional[str]
    created_at: datetime


class TransactionCreate(BaseModel):
    transaction_date: DateT
    amount: Optional[float] = Field(default=None, ge=0)
    kind: str = Field(
        default="vente",
        pattern="^(vente|succession|donation|autre)$",
    )
    source: Optional[str] = Field(default=None, max_length=64)
    notes: Optional[str] = None


@router.get(
    "/{lead_id}/transactions",
    response_model=List[TransactionRead],
)
async def list_transactions(
    lead_id: int, db: DBSession, _: CurrentUser
) -> List[TransactionRead]:
    from app.models.prospection_lead_transaction import (
        ProspectionLeadTransaction,
    )

    rows = (
        await db.execute(
            select(ProspectionLeadTransaction)
            .where(ProspectionLeadTransaction.lead_id == lead_id)
            .order_by(ProspectionLeadTransaction.transaction_date.desc())
        )
    ).scalars().all()
    return [TransactionRead.model_validate(r) for r in rows]


@router.post(
    "/{lead_id}/transactions",
    response_model=TransactionRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_transaction(
    lead_id: int,
    data: TransactionCreate,
    db: DBSession,
    _: CurrentUser,
) -> TransactionRead:
    from app.models.prospection_lead_transaction import (
        ProspectionLeadTransaction,
    )

    # Vérifie que le lead existe
    exists = (
        await db.execute(
            select(ProspectionLead.id).where(
                ProspectionLead.id == lead_id
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(404, "Prospect introuvable")

    tr = ProspectionLeadTransaction(
        lead_id=lead_id,
        transaction_date=data.transaction_date,
        amount=data.amount,
        kind=data.kind,
        source=(data.source or "").strip() or None,
        notes=(data.notes or "").strip() or None,
    )
    db.add(tr)
    await db.flush()
    await db.refresh(tr)
    return TransactionRead.model_validate(tr)


@router.delete(
    "/transactions/{tx_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_transaction(
    tx_id: int, db: DBSession, _: CurrentUser
) -> None:
    from app.models.prospection_lead_transaction import (
        ProspectionLeadTransaction,
    )

    res = await db.execute(
        delete(ProspectionLeadTransaction).where(
            ProspectionLeadTransaction.id == tx_id
        )
    )
    if (res.rowcount or 0) == 0:
        raise HTTPException(404, "Transaction introuvable")


# ------------------------ Owner aggregation (Option C) ------------------------
#
# Donne une vue unifiée de tous les immeubles d'un même propriétaire,
# sans splitter le modèle. Le propriétaire est identifié soit par
# son NEQ (corporation), soit par un nom normalisé (particulier).
# La timeline FollowUp est unifiée à travers tous les leads du proprio.


import re as _re_owner
import unicodedata as _ud_owner


def _normalize_owner_name(name: str) -> str:
    """Forme canonique d'un nom de proprio pour matching et URL.

    « Steven Tremblay » et « tremblay, steven » donnent la même clé.
    Garde les espaces comme `-` pour rester URL-safe.
    """
    if not name:
        return ""
    s = "".join(
        c
        for c in _ud_owner.normalize("NFKD", name)
        if not _ud_owner.combining(c)
    )
    s = s.lower().strip()
    s = _re_owner.sub(r"[^a-z0-9 ]+", " ", s)
    s = _re_owner.sub(r"\s+", " ", s).strip()
    return s.replace(" ", "-")


class OwnerLeadMini(BaseModel):
    id: int
    name: str
    address: Optional[str]
    city: Optional[str]
    status: str
    score: int
    nb_logements: Optional[int]
    valeur_fonciere: Optional[float]


class OwnerFollowUp(BaseModel):
    id: int
    lead_id: int
    lead_name: str
    kind: str
    direction: str
    outcome: str
    notes: Optional[str]
    performed_at: datetime
    next_action_at: Optional[datetime]
    next_action_label: Optional[str]


class OwnerView(BaseModel):
    """Vue agrégée d'un propriétaire — sans persisting un OwnerProfile.

    Calculé à la volée depuis les leads matchant le NEQ ou le nom
    normalisé. Rapide tant que le proprio n'a pas >100 immeubles."""

    key: str  # "neq:1234567890" ou "name:steven-tremblay"
    key_type: str  # "neq" | "name"
    owner_name: Optional[str]
    owner_kind: str
    owner_phone: Optional[str]
    owner_email: Optional[str]
    owner_address: Optional[str]
    owner_neq: Optional[str]
    leads_count: int
    leads: List[OwnerLeadMini]
    total_logements: Optional[int]
    total_valeur_fonciere: Optional[float]
    timeline: List[OwnerFollowUp]
    next_action_at: Optional[datetime]


async def _build_owner_view(
    db, leads: List[ProspectionLead], key: str, key_type: str
) -> OwnerView:
    if not leads:
        return OwnerView(
            key=key,
            key_type=key_type,
            owner_name=None,
            owner_kind="inconnu",
            owner_phone=None,
            owner_email=None,
            owner_address=None,
            owner_neq=None,
            leads_count=0,
            leads=[],
            total_logements=None,
            total_valeur_fonciere=None,
            timeline=[],
            next_action_at=None,
        )

    # Le owner_* est dupliqué sur chaque lead — on prend le plus récent
    # comme source de vérité (souvent le mieux renseigné).
    leads_sorted = sorted(
        leads,
        key=lambda l: (l.last_contacted_at or l.created_at),
        reverse=True,
    )
    primary = leads_sorted[0]

    total_log = sum(
        (l.nb_logements or 0) for l in leads if l.nb_logements
    ) or None
    total_val = (
        sum(float(l.valeur_fonciere) for l in leads if l.valeur_fonciere)
        or None
    )

    leads_mini = [
        OwnerLeadMini(
            id=l.id,
            name=l.name,
            address=l.address,
            city=l.city,
            status=l.status,
            score=l.score or 0,
            nb_logements=l.nb_logements,
            valeur_fonciere=(
                float(l.valeur_fonciere)
                if l.valeur_fonciere is not None
                else None
            ),
        )
        for l in leads_sorted
    ]

    # Timeline : toutes les FollowUp sur ces leads, triées chrono-desc.
    from app.models.follow_up import FollowUp

    lead_ids = [l.id for l in leads]
    name_by_lead = {l.id: l.name for l in leads}
    fu_rows = []
    if lead_ids:
        fu_rows = (
            await db.execute(
                select(FollowUp)
                .where(
                    FollowUp.subject_type == "prospect",
                    FollowUp.subject_id.in_(lead_ids),
                )
                .order_by(FollowUp.performed_at.desc())
                .limit(500)
            )
        ).scalars().all()

    timeline = [
        OwnerFollowUp(
            id=f.id,
            lead_id=f.subject_id,
            lead_name=name_by_lead.get(f.subject_id, f"Lead #{f.subject_id}"),
            kind=f.kind,
            direction=f.direction,
            outcome=f.outcome,
            notes=f.notes,
            performed_at=f.performed_at,
            next_action_at=f.next_action_at,
            next_action_label=f.next_action_label,
        )
        for f in fu_rows
    ]

    # Prochaine action prévue (la + proche dans le futur)
    now = datetime.now(timezone.utc)
    upcoming = [
        f.next_action_at for f in fu_rows
        if f.next_action_at and f.next_action_at >= now
        and f.outcome not in ("won", "lost", "not_interested")
    ]
    next_action = min(upcoming) if upcoming else None

    return OwnerView(
        key=key,
        key_type=key_type,
        owner_name=primary.owner_name,
        owner_kind=primary.owner_kind,
        owner_phone=primary.owner_phone,
        owner_email=primary.owner_email,
        owner_address=primary.owner_address,
        owner_neq=primary.owner_neq,
        leads_count=len(leads),
        leads=leads_mini,
        total_logements=total_log,
        total_valeur_fonciere=total_val,
        timeline=timeline,
        next_action_at=next_action,
    )


class Canada411Result(BaseModel):
    name: str
    address: Optional[str] = None
    phone: str
    source: str = "canada411"
    source_url: str


@router.get(
    "/{lead_id}/canada411-lookup",
    response_model=List[Canada411Result],
    summary="Cherche le téléphone du propriétaire dans Canada411 par "
    "nom + ville (extraits du lead). Pas de cache : le scraping est "
    "rapide (~1s) et les résultats peuvent évoluer.",
)
async def canada411_lookup(
    lead_id: int,
    db: DBSession,
    _: CurrentUser,
) -> List[Canada411Result]:
    from app.integrations.canada411 import lookup_by_name

    lead = await db.get(ProspectionLead, lead_id)
    if lead is None:
        raise HTTPException(404, "Lead introuvable.")
    if not lead.owner_name:
        raise HTTPException(
            400,
            "Le lead n'a pas de nom de propriétaire. Documente le "
            "proprio d'abord (via REQ ou EvalWeb).",
        )
    # Si le proprio est une corporation (NEQ), on n'utilise pas
    # Canada411 (les corps n'y figurent pas) — REQ donne déjà le tel.
    results = await lookup_by_name(
        lead.owner_name,
        city=lead.city or "Montreal",
    )
    return [Canada411Result(**r) for r in results]


@router.post(
    "/{lead_id}/apply-phone",
    summary="Sauve un téléphone trouvé (Canada411 ou autre) sur le lead.",
)
async def apply_phone(
    lead_id: int,
    db: DBSession,
    _: CurrentUser,
    phone: str = Query(..., min_length=8, max_length=32),
) -> dict:
    lead = await db.get(ProspectionLead, lead_id)
    if lead is None:
        raise HTTPException(404, "Lead introuvable.")
    lead.owner_phone = phone.strip()[:50]
    await db.flush()
    return {"ok": True, "phone": lead.owner_phone}


@router.get(
    "/owners/by-neq/{neq}",
    response_model=OwnerView,
    summary="Vue agrégée d'un propriétaire-corporation : tous ses "
    "immeubles + timeline cross-property unifiée.",
)
async def owner_by_neq(
    neq: str, db: DBSession, _: CurrentUser
) -> OwnerView:
    leads = (
        await db.execute(
            select(ProspectionLead).where(
                ProspectionLead.owner_neq == neq,
                ProspectionLead.archived.is_(False),
            )
        )
    ).scalars().all()
    return await _build_owner_view(
        db, list(leads), key=f"neq:{neq}", key_type="neq"
    )


@router.get(
    "/owners/by-name/{name_norm}",
    response_model=OwnerView,
    summary="Vue agrégée d'un propriétaire-particulier (matching par "
    "nom normalisé). Le name_norm est le nom passé à _normalize_owner_name.",
)
async def owner_by_name(
    name_norm: str, db: DBSession, _: CurrentUser
) -> OwnerView:
    # On charge tous les leads non archivés et on filtre côté Python
    # parce que la normalisation Postgres serait complexe (ILIKE +
    # unaccent). À ~1000 leads, c'est instantané.
    rows = (
        await db.execute(
            select(ProspectionLead).where(
                ProspectionLead.archived.is_(False),
                ProspectionLead.owner_name.is_not(None),
            )
        )
    ).scalars().all()
    matching = [
        l
        for l in rows
        if _normalize_owner_name(l.owner_name or "") == name_norm
    ]
    return await _build_owner_view(
        db, matching, key=f"name:{name_norm}", key_type="name"
    )


# ------------------------ Buy-flow actions ------------------------


class Relance6mIn(BaseModel):
    notes: Optional[str] = None


@router.post(
    "/{lead_id}/relance-6m",
    response_model=LeadRead,
    summary="Marque le lead comme « Perdu (refus) » et programme une "
    "relance automatique dans 180 jours. Le lead réapparaîtra dans "
    "la queue overdue à ce moment-là.",
)
async def relance_6_months(
    lead_id: int,
    payload: Relance6mIn,
    db: DBSession,
    user: CurrentUser,
) -> LeadRead:
    from app.models.follow_up import FollowUp

    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")

    # Marque perdu
    lead.status = ProspectionLeadStatus.PERDU.value

    # Crée un FollowUp auto à +180 jours pour qu'il revienne dans la queue
    next_at = datetime.now(timezone.utc) + __import__("datetime").timedelta(
        days=180
    )
    db.add(
        FollowUp(
            subject_type="prospect",
            subject_id=lead_id,
            kind="auto",
            direction="outbound",
            outcome="scheduled",
            notes=(payload.notes or "Refus initial — relance dans 6 mois.")[:1000],
            performed_by_user_id=user.id,
            next_action_at=next_at,
            next_action_label="Relance 6 mois après refus",
        )
    )
    apply_score(lead)
    await db.flush()
    await db.refresh(lead)

    photos_count = await _photos_count_for(db, lead_id)
    return _serialize(lead, photos_count, 0)


# ------------------------ Nearby addresses (GPS suggestions) ------------------------


@router.get(
    "/nearby-addresses",
    summary="Retourne 5 adresses civiques voisines d'un point GPS — "
    "utile sur le mode drive-by pour confirmer l'adresse exacte.",
)
async def nearby_addresses(
    lat: float = Query(...),
    lng: float = Query(...),
    radius_m: int = Query(default=30, ge=10, le=100),
    _: CurrentUser = None,
) -> list:
    """Interroge l'Overpass API d'OSM pour les adresses civiques dans
    un rayon de N mètres. Gratuit, pas de clé.

    Retourne : [{label, address, city, postal_code, lat, lng}].
    """
    import httpx

    # Overpass query: tout les nodes/ways avec addr:housenumber dans
    # un rayon autour du point.
    query = f"""
    [out:json][timeout:8];
    (
      node["addr:housenumber"](around:{radius_m},{lat},{lng});
      way["addr:housenumber"](around:{radius_m},{lat},{lng});
    );
    out center 12;
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": query},
                headers={
                    "User-Agent": "h2.0-Horizon/1.0 (contact@immohorizon.com)"
                },
            )
            if r.status_code != 200:
                return []
            data = r.json()
    except httpx.HTTPError:
        return []

    out = []
    seen: set[str] = set()
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        hn = tags.get("addr:housenumber") or ""
        st = tags.get("addr:street") or ""
        if not hn or not st:
            continue
        addr = f"{hn} {st}".strip()
        if addr in seen:
            continue
        seen.add(addr)
        if el.get("type") == "node":
            elat = el.get("lat")
            elng = el.get("lon")
        else:
            center = el.get("center", {})
            elat = center.get("lat")
            elng = center.get("lon")
        out.append(
            {
                "label": addr,
                "address": addr,
                "city": tags.get("addr:city") or None,
                "postal_code": tags.get("addr:postcode") or None,
                "lat": elat,
                "lng": elng,
            }
        )
        if len(out) >= 5:
            break
    return out


# ------------------------ JLR PDF importer ------------------------


@router.post(
    "/{lead_id}/import-jlr-pdf",
    summary="Upload un PDF JLR (rapport sur droit immobilier) et "
    "extrait automatiquement transactions, propriétaire, hypothèque.",
)
async def import_jlr_pdf(
    lead_id: int,
    db: DBSession,
    _: CurrentUser,
    pdf: UploadFile = File(...),
) -> dict:
    """Parser PDF basique : extrait le texte avec pypdf, regex pour
    repérer les patterns de transactions et hypothèques. Précision
    ~70-80 % sur des PDFs JLR standards. L'utilisateur valide les
    données extraites avant qu'elles soient écrites.

    Pour l'instant : extrait le texte brut + retourne les chaînes
    candidates. La V2 aura un parser dédié JLR.
    """
    if not (pdf.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "Le fichier doit être un PDF.")
    blob = await pdf.read()
    if not blob:
        raise HTTPException(400, "PDF vide.")
    if len(blob) > 20 * 1024 * 1024:
        raise HTTPException(413, "PDF trop volumineux (max 20 Mo).")

    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(404, "Prospect introuvable")

    # Parsing PDF
    try:
        from pypdf import PdfReader
        import io as _io

        reader = PdfReader(_io.BytesIO(blob))
        text = "\n".join(
            (page.extract_text() or "") for page in reader.pages
        )
    except Exception as exc:
        raise HTTPException(
            500, f"Échec du parsing PDF : {exc}"
        ) from exc

    import re as _re
    from app.models.prospection_lead_transaction import (
        ProspectionLeadTransaction,
    )

    # Détection des transactions : pattern « date AAAA-MM-JJ ... montant »
    tx_pattern = _re.compile(
        r"(\d{4}[-/]\d{2}[-/]\d{2})[\s\S]{0,200}?(\d{1,3}(?:[ ,]\d{3})*(?:[.,]\d{2})?)\s*\$?",
        _re.IGNORECASE,
    )
    # Détection hypothèque : « hypothèque ... montant »
    mortgage_pattern = _re.compile(
        r"hypoth[eè]que[\s\S]{0,200}?(\d{1,3}(?:[ ,]\d{3})*(?:[.,]\d{2})?)",
        _re.IGNORECASE,
    )
    # Propriétaire actuel
    owner_pattern = _re.compile(
        r"propri[eé]taire(?:\s+actuel)?[\s:]+([A-ZÀ-Ü][A-Za-zÀ-ü\s,.\-]{3,80})",
        _re.IGNORECASE,
    )

    found_transactions = []
    for m in tx_pattern.finditer(text):
        date_s = m.group(1).replace("/", "-")
        amount_s = (
            m.group(2)
            .replace(" ", "")
            .replace(",", "")
            .replace(" ", "")
        )
        try:
            from datetime import date as _D

            d = _D.fromisoformat(date_s[:10])
            amt = float(amount_s)
            if 1000 <= amt <= 100_000_000:  # plage plausible
                found_transactions.append(
                    {
                        "transaction_date": d.isoformat(),
                        "amount": amt,
                        "kind": "vente",
                        "source": "JLR PDF (auto-extrait)",
                    }
                )
        except (ValueError, TypeError):
            continue

    # Insère uniquement si liste non vide ; dédoublonne sur (date, amount)
    existing_keys = set()
    if found_transactions:
        existing = (
            await db.execute(
                select(ProspectionLeadTransaction).where(
                    ProspectionLeadTransaction.lead_id == lead_id
                )
            )
        ).scalars().all()
        existing_keys = {
            (e.transaction_date.isoformat(), float(e.amount or 0))
            for e in existing
        }

    inserted = 0
    for tx in found_transactions[:20]:  # max 20 pour éviter le bruit
        key = (tx["transaction_date"], tx["amount"])
        if key in existing_keys:
            continue
        from datetime import date as _D

        db.add(
            ProspectionLeadTransaction(
                lead_id=lead_id,
                transaction_date=_D.fromisoformat(tx["transaction_date"]),
                amount=tx["amount"],
                kind=tx["kind"],
                source=tx["source"],
            )
        )
        existing_keys.add(key)
        inserted += 1

    # Tente d'extraire l'hypothèque la plus probable
    suggested_mortgage = None
    mortgage_match = mortgage_pattern.search(text)
    if mortgage_match:
        try:
            v = float(
                mortgage_match.group(1)
                .replace(" ", "")
                .replace(",", "")
                .replace(" ", "")
            )
            if 1000 <= v <= 100_000_000:
                suggested_mortgage = v
        except (ValueError, TypeError):
            pass

    # Owner suggestion
    suggested_owner = None
    owner_match = owner_pattern.search(text)
    if owner_match:
        suggested_owner = owner_match.group(1).strip()[:200]

    await db.flush()

    return {
        "transactions_inserted": inserted,
        "transactions_found": len(found_transactions),
        "suggested_mortgage_balance": suggested_mortgage,
        "suggested_owner_name": suggested_owner,
        "text_length": len(text),
        "notes": [
            "Parsing automatique du PDF — précision approximative.",
            "Vérifie les transactions ajoutées et les suggestions ci-dessus.",
            "Hypothèque/propriétaire ne sont PAS auto-appliqués — copie-les manuellement si correct.",
        ],
    }
