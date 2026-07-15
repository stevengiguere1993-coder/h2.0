"""Pipeline « Locations » (relocation / vacances) — Gestion locative.

Un LocationDossier suit la relocation d'un logement : le locataire
confirme son départ → annonce(s) publiée(s) → visites de candidats →
candidat retenu → reloué (nouveau bail signé ailleurs). Tout est
consigné À LA MAIN par l'employé — aucun automatisme externe.

Endpoints :
    GET    /immobilier/locations/overview   (KPIs + dossiers enrichis)
    POST   /immobilier/locations            (créer un dossier)
    PATCH  /immobilier/locations/{id}
    DELETE /immobilier/locations/{id}
    POST   /immobilier/locations/{id}/annonces
    PATCH  /immobilier/locations/annonces/{id}
    DELETE /immobilier/locations/annonces/{id}
    POST   /immobilier/locations/{id}/visites
    PATCH  /immobilier/locations/visites/{id}
    DELETE /immobilier/locations/visites/{id}
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.permissions import visible_immeuble_ids
from app.models.immobilier import (
    Bail,
    Immeuble,
    Locataire,
    LocationAnnonce,
    LocationDossier,
    LocationDossierStatut,
    LocationVisite,
    Logement,
    LogementStatus,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/immobilier", tags=["immobilier-locations"])

STATUTS_ACTIFS = {
    LocationDossierStatut.AVIS_RECU.value,
    LocationDossierStatut.ANNONCE_PUBLIEE.value,
    LocationDossierStatut.VISITES.value,
    LocationDossierStatut.CANDIDAT_RETENU.value,
}

STATUTS_VALIDES = {s.value for s in LocationDossierStatut}


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion immobilière » non autorisé.",
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Schemas ────────────────────────────────────────────────────────────


class AnnonceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dossier_id: int
    plateforme: str
    url: Optional[str] = None
    publiee_le: Optional[date] = None
    active: bool


class AnnonceCreate(BaseModel):
    plateforme: str = Field(..., min_length=1, max_length=64)
    url: Optional[str] = Field(default=None, max_length=1000)
    publiee_le: Optional[date] = None


class AnnonceUpdate(BaseModel):
    plateforme: Optional[str] = Field(default=None, max_length=64)
    url: Optional[str] = Field(default=None, max_length=1000)
    publiee_le: Optional[date] = None
    active: Optional[bool] = None


class VisiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dossier_id: int
    quand: Optional[datetime] = None
    candidat_nom: str
    candidat_contact: Optional[str] = None
    statut: str
    interesse: Optional[bool] = None
    notes: Optional[str] = None


class VisiteCreate(BaseModel):
    quand: Optional[datetime] = None
    candidat_nom: str = Field(..., min_length=1, max_length=255)
    candidat_contact: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = None


class VisiteUpdate(BaseModel):
    quand: Optional[datetime] = None
    candidat_nom: Optional[str] = Field(default=None, max_length=255)
    candidat_contact: Optional[str] = Field(default=None, max_length=255)
    statut: Optional[str] = Field(default=None, max_length=16)
    interesse: Optional[bool] = None
    notes: Optional[str] = None


class DossierRow(BaseModel):
    id: int
    logement_id: int
    logement_numero: str
    immeuble_id: int
    immeuble_name: str
    bail_id: Optional[int] = None
    locataire_sortant: Optional[str] = None
    statut: str
    date_depart: Optional[date] = None
    loyer_demande: Optional[float] = None
    loyer_ancien: Optional[float] = None
    reloue_le: Optional[date] = None
    notes: Optional[str] = None
    annonces: List[AnnonceRead] = Field(default_factory=list)
    visites: List[VisiteRead] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class LocationsOverview(BaseModel):
    rows: List[DossierRow] = Field(default_factory=list)
    nb_actifs: int = 0
    nb_annonces_actives: int = 0
    nb_visites_a_venir: int = 0
    nb_reloues_90j: int = 0


class DossierCreate(BaseModel):
    logement_id: int
    bail_id: Optional[int] = None
    date_depart: Optional[date] = None
    loyer_demande: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None


class DossierUpdate(BaseModel):
    statut: Optional[str] = Field(default=None, max_length=24)
    date_depart: Optional[date] = None
    loyer_demande: Optional[float] = Field(default=None, ge=0)
    reloue_le: Optional[date] = None
    notes: Optional[str] = None


# ─── Helpers ────────────────────────────────────────────────────────────


async def _dossier_or_404(db, dossier_id: int) -> LocationDossier:
    obj = await db.get(LocationDossier, dossier_id)
    if obj is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Dossier de location introuvable."
        )
    return obj


async def _to_row(db, d: LocationDossier) -> DossierRow:
    lg = await db.get(Logement, d.logement_id)
    im = await db.get(Immeuble, lg.immeuble_id) if lg else None
    locataire_sortant = None
    if d.bail_id:
        bail = await db.get(Bail, d.bail_id)
        if bail:
            loc = await db.get(Locataire, bail.locataire_id)
            locataire_sortant = loc.full_name if loc else None
    annonces = (
        await db.execute(
            select(LocationAnnonce)
            .where(LocationAnnonce.dossier_id == d.id)
            .order_by(LocationAnnonce.id.asc())
        )
    ).scalars().all()
    visites = (
        await db.execute(
            select(LocationVisite)
            .where(LocationVisite.dossier_id == d.id)
            .order_by(LocationVisite.quand.asc().nulls_last())
        )
    ).scalars().all()
    return DossierRow(
        id=d.id,
        logement_id=d.logement_id,
        logement_numero=(lg.numero if lg else f"#{d.logement_id}"),
        immeuble_id=(im.id if im else 0),
        immeuble_name=(im.name if im else "—"),
        bail_id=d.bail_id,
        locataire_sortant=locataire_sortant,
        statut=d.statut,
        date_depart=d.date_depart,
        loyer_demande=(
            float(d.loyer_demande) if d.loyer_demande is not None else None
        ),
        loyer_ancien=(
            float(d.loyer_ancien) if d.loyer_ancien is not None else None
        ),
        reloue_le=d.reloue_le,
        notes=d.notes,
        annonces=[AnnonceRead.model_validate(a) for a in annonces],
        visites=[VisiteRead.model_validate(v) for v in visites],
        created_at=d.created_at,
    )


# ─── Overview ───────────────────────────────────────────────────────────


@router.get("/locations/overview", response_model=LocationsOverview)
async def locations_overview(
    db: DBSession,
    user: CurrentUser,
    entreprise_id: Optional[int] = None,
    immeuble_id: Optional[int] = None,
) -> LocationsOverview:
    """Tous les dossiers de relocation visibles (actifs d'abord), avec
    agrégats. Immeubles en gestion externe exclus : la relocation y
    relève du gestionnaire tiers."""
    _require_volet(user)

    imm_q = select(Immeuble).where(Immeuble.gestion_externe.isnot(True))
    if entreprise_id is not None:
        imm_q = imm_q.where(Immeuble.owner_entreprise_id == int(entreprise_id))
    if immeuble_id is not None:
        imm_q = imm_q.where(Immeuble.id == int(immeuble_id))
    immeubles = (await db.execute(imm_q)).scalars().all()
    visible = await visible_immeuble_ids(db, user)
    if visible is not None:
        immeubles = [i for i in immeubles if i.id in visible]
    imm_ids = [i.id for i in immeubles]
    if not imm_ids:
        return LocationsOverview()

    logement_ids = [
        row[0]
        for row in (
            await db.execute(
                select(Logement.id).where(Logement.immeuble_id.in_(imm_ids))
            )
        ).all()
    ]
    if not logement_ids:
        return LocationsOverview()

    dossiers = (
        await db.execute(
            select(LocationDossier)
            .where(LocationDossier.logement_id.in_(logement_ids))
            .order_by(LocationDossier.created_at.desc())
        )
    ).scalars().all()

    rows = [await _to_row(db, d) for d in dossiers]
    # Actifs d'abord, puis complétés/annulés (déjà triés par création desc).
    rows.sort(key=lambda r: 0 if r.statut in STATUTS_ACTIFS else 1)

    now = _now()
    today = now.date()
    nb_annonces_actives = sum(
        1
        for r in rows
        if r.statut in STATUTS_ACTIFS
        for a in r.annonces
        if a.active
    )
    nb_visites_a_venir = sum(
        1
        for r in rows
        if r.statut in STATUTS_ACTIFS
        for v in r.visites
        if v.statut == "planifiee" and (v.quand is None or v.quand >= now)
    )
    return LocationsOverview(
        rows=rows,
        nb_actifs=sum(1 for r in rows if r.statut in STATUTS_ACTIFS),
        nb_annonces_actives=nb_annonces_actives,
        nb_visites_a_venir=nb_visites_a_venir,
        nb_reloues_90j=sum(
            1
            for r in rows
            if r.statut == LocationDossierStatut.RELOUE.value
            and r.reloue_le is not None
            and r.reloue_le >= today - timedelta(days=90)
        ),
    )


# ─── CRUD dossier ───────────────────────────────────────────────────────


@router.post(
    "/locations",
    response_model=DossierRow,
    status_code=status.HTTP_201_CREATED,
)
async def create_dossier(
    payload: DossierCreate, db: DBSession, user: CurrentUser
) -> DossierRow:
    """Ouvre un dossier de relocation. Si un bail sortant est fourni,
    photographie son loyer (delta affichable) et propose sa fin comme
    date de départ."""
    _require_volet(user)
    lg = await db.get(Logement, payload.logement_id)
    if lg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Logement introuvable.")

    # Un seul dossier ACTIF par logement — sinon on s'y perd.
    existing = (
        await db.execute(
            select(LocationDossier).where(
                LocationDossier.logement_id == payload.logement_id,
                LocationDossier.statut.in_(list(STATUTS_ACTIFS)),
            )
        )
    ).scalars().first()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Une relocation est déjà en cours pour ce logement.",
        )

    loyer_ancien = None
    date_depart = payload.date_depart
    if payload.bail_id:
        bail = await db.get(Bail, payload.bail_id)
        if bail is not None:
            loyer_ancien = (
                float(bail.loyer_mensuel)
                if bail.loyer_mensuel is not None
                else None
            )
            if date_depart is None:
                date_depart = bail.date_fin

    obj = LocationDossier(
        logement_id=payload.logement_id,
        bail_id=payload.bail_id,
        date_depart=date_depart,
        loyer_demande=(
            payload.loyer_demande
            if payload.loyer_demande is not None
            else (
                float(lg.loyer_demande)
                if lg.loyer_demande is not None
                else loyer_ancien
            )
        ),
        loyer_ancien=loyer_ancien,
        notes=payload.notes,
    )
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return await _to_row(db, obj)


@router.patch("/locations/{dossier_id}", response_model=DossierRow)
async def update_dossier(
    dossier_id: int,
    payload: DossierUpdate,
    db: DBSession,
    user: CurrentUser,
) -> DossierRow:
    _require_volet(user)
    obj = await _dossier_or_404(db, dossier_id)
    data = payload.model_dump(exclude_unset=True)
    if "statut" in data and data["statut"] not in STATUTS_VALIDES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Statut invalide."
        )
    for k, v in data.items():
        setattr(obj, k, v)
    # Passage à « reloué » : date automatique + le logement redevient
    # occupé (interconnexion — le nouveau bail se crée sur le logement).
    if data.get("statut") == LocationDossierStatut.RELOUE.value:
        if obj.reloue_le is None:
            obj.reloue_le = _now().date()
        lg = await db.get(Logement, obj.logement_id)
        if lg is not None:
            lg.status = LogementStatus.OCCUPE.value
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return await _to_row(db, obj)


@router.delete(
    "/locations/{dossier_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_dossier(
    dossier_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await _dossier_or_404(db, dossier_id)
    await db.delete(obj)
    await db.commit()


# ─── Annonces ───────────────────────────────────────────────────────────


@router.post(
    "/locations/{dossier_id}/annonces",
    response_model=AnnonceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_annonce(
    dossier_id: int,
    payload: AnnonceCreate,
    db: DBSession,
    user: CurrentUser,
) -> AnnonceRead:
    _require_volet(user)
    dossier = await _dossier_or_404(db, dossier_id)
    obj = LocationAnnonce(
        dossier_id=dossier.id,
        plateforme=payload.plateforme.strip(),
        url=(payload.url or "").strip() or None,
        publiee_le=payload.publiee_le or _now().date(),
    )
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    # Première annonce sur un dossier « départ confirmé » → il passe
    # naturellement à « annonce publiée ».
    if dossier.statut == LocationDossierStatut.AVIS_RECU.value:
        dossier.statut = LocationDossierStatut.ANNONCE_PUBLIEE.value
        dossier.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return AnnonceRead.model_validate(obj)


@router.patch("/locations/annonces/{annonce_id}", response_model=AnnonceRead)
async def update_annonce(
    annonce_id: int,
    payload: AnnonceUpdate,
    db: DBSession,
    user: CurrentUser,
) -> AnnonceRead:
    _require_volet(user)
    obj = await db.get(LocationAnnonce, annonce_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annonce introuvable.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return AnnonceRead.model_validate(obj)


@router.delete(
    "/locations/annonces/{annonce_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_annonce(
    annonce_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(LocationAnnonce, annonce_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annonce introuvable.")
    await db.delete(obj)
    await db.commit()


# ─── Visites ────────────────────────────────────────────────────────────


@router.post(
    "/locations/{dossier_id}/visites",
    response_model=VisiteRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_visite(
    dossier_id: int,
    payload: VisiteCreate,
    db: DBSession,
    user: CurrentUser,
) -> VisiteRead:
    _require_volet(user)
    dossier = await _dossier_or_404(db, dossier_id)
    obj = LocationVisite(
        dossier_id=dossier.id,
        quand=payload.quand,
        candidat_nom=payload.candidat_nom.strip(),
        candidat_contact=(payload.candidat_contact or "").strip() or None,
        notes=payload.notes,
    )
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    # Première visite → le dossier passe à « visites en cours ».
    if dossier.statut in (
        LocationDossierStatut.AVIS_RECU.value,
        LocationDossierStatut.ANNONCE_PUBLIEE.value,
    ):
        dossier.statut = LocationDossierStatut.VISITES.value
        dossier.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return VisiteRead.model_validate(obj)


@router.patch("/locations/visites/{visite_id}", response_model=VisiteRead)
async def update_visite(
    visite_id: int,
    payload: VisiteUpdate,
    db: DBSession,
    user: CurrentUser,
) -> VisiteRead:
    _require_volet(user)
    obj = await db.get(LocationVisite, visite_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Visite introuvable.")
    data = payload.model_dump(exclude_unset=True)
    if "statut" in data and data["statut"] not in (
        "planifiee", "faite", "absent", "annulee"
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Statut de visite invalide."
        )
    for k, v in data.items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return VisiteRead.model_validate(obj)


@router.delete(
    "/locations/visites/{visite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_visite(
    visite_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(LocationVisite, visite_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Visite introuvable.")
    await db.delete(obj)
    await db.commit()
