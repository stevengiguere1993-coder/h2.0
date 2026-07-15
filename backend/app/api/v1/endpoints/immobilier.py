"""Volet Gestion immobilière — CRUD + KPIs financiers.

Restreint au volet `immobilier` (whitelist côté User.volets).

Couvre :
- Immeubles + ownership multi-entreprises
- Logements (avec statut : occupé / vacant / réservé / hors-loc)
- Locataires
- Baux + paiements de loyer
- Hypothèques
- Évaluations (municipale, marchande, appraisal)
- Maintenance (ordres de travail)
- KPIs financiers (revenu brut, GRM, cap rate, cash flow, appréciation)
- Import-matricule depuis mtl_property_units pour pré-remplir
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.permissions import visible_immeuble_ids
from app.core.security import decode_token
from app.repositories.user import UserRepository

from app.api.deps import CurrentUser, DBSession
from app.models.user import User
from app.services.permissions_service import require_capability
from app.models.entreprise import Entreprise
from app.models.bon_travail import BonTravail
from app.models.client import Client
from app.models.employe import Employe
from app.models.project import Project
from app.models.project_phase import ProjectPhase
from app.models.project_photo import ProjectPhoto
from app.models.sous_traitant import SousTraitant
from app.models.immobilier import (
    Bail,
    BailRenouvellement,
    DepenseImmeuble,
    BailStatus,
    Evaluation,
    EvaluationKind,
    Hypotheque,
    HypothequeStatus,
    Immeuble,
    ImmeubleOwnership,
    ImmeubleType,
    Logement,
    LogementStatus,
    Locataire,
    LocataireCommunication,
    MaintenanceOrdre,
    PaiementLoyer,
    RelanceLoyer,
)
from app.models.montreal_property_unit import MontrealPropertyUnit
from app.schemas.immobilier import (
    BailCreate,
    BailRead,
    BailUpdate,
    EvaluationCreate,
    EvaluationRead,
    EvaluationUpdate,
    HypothequeCreate,
    HypothequeRead,
    HypothequeUpdate,
    ImmeubleCreate,
    ImmeubleFinancials,
    ImmeubleImportFromMatriculeRequest,
    ImmeubleImportResult,
    ImmeubleListItem,
    ImmeubleOwnershipCreate,
    ImmeubleOwnershipRead,
    ImmeubleRead,
    ImmeubleUpdate,
    LocataireCommunicationCreate,
    LocataireCommunicationRead,
    LocataireCreate,
    LocataireDossier,
    LocataireRead,
    LocataireUpdate,
    DossierBail,
    DossierPaiement,
    DossierRenouvellement,
    LogementCreate,
    LogementDossier,
    LogementDossierBail,
    LogementDossierBon,
    LogementDossierImmeuble,
    LogementDossierLocataire,
    LogementRead,
    LogementUpdate,
    LoyerPoint,
    MaintenanceOrdreCreate,
    MaintenanceOrdreRead,
    MaintenanceOrdreUpdate,
    MaintenanceOverview,
    MaintenanceOverviewRow,
    PaiementLoyerCreate,
    PaiementLoyerRead,
    PlexImportBuilding,
    PlexImportCompany,
    PlexImportCreated,
    PlexImportRequest,
    PlexImportResult,
    PlexImportUnit,
)
from app.services.plexflow_import import parse_plexflow


log = logging.getLogger(__name__)
router = APIRouter(prefix="/immobilier", tags=["immobilier"])

# Routeur SANS la garde Bearer de niveau routeur (DEP_IMMOBILIER) : les
# endpoints d'images s'authentifient EUX-MÊMES via `?t=<jwt>` parce que
# `<img src>` ne peut pas envoyer de header Authorization. La garde de
# routeur ajoutée par la refonte permissions (P2b) bloquait ces requêtes
# en 401 avant même d'atteindre l'endpoint → photos d'immeubles cassées
# (retour Phil 2026-07-10). La sécurité reste équivalente :
# _resolve_user_for_image() valide le JWT + _require_volet().
router_images = APIRouter(prefix="/immobilier", tags=["immobilier"])


# ── Helpers ─────────────────────────────────────────────────────────────


def _require_volet(user: CurrentUser) -> None:
    """Refuse l'accès si l'utilisateur n'a pas le volet immobilier."""
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion immobilière » non autorisé pour cet utilisateur.",
        )


async def _require_immeuble_visible(db, user, immeuble_id: int) -> None:
    """Refuse l'accès à un immeuble si l'utilisateur (employé) n'y est pas
    affecté. Les rôles manager+ voient tout (visible == None)."""
    visible = await visible_immeuble_ids(db, user)
    if visible is not None and immeuble_id not in visible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès à cet immeuble non autorisé.",
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_immeuble_or_404(db, immeuble_id: int) -> Immeuble:
    obj = await db.get(Immeuble, immeuble_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Immeuble {immeuble_id} introuvable.",
        )
    return obj


def _immeuble_to_read(obj: Immeuble) -> ImmeubleRead:
    """Sérialise un Immeuble en exposant `has_cover_photo` sans charger le blob."""
    out = ImmeubleRead.model_validate(obj, from_attributes=True)
    # `cover_photo_blob` est deferred ; si la colonne n'a pas encore été
    # touchée la valeur sera None et on ne déclenche pas de chargement.
    state = getattr(obj, "__dict__", {})
    has_blob = bool(state.get("cover_photo_blob") or obj.cover_photo_content_type)
    out.has_cover_photo = has_blob
    return out


# ── Alertes « À surveiller » (configurables) ────────────────────────────
# Config globale du pôle, stockée dans automation_settings (clé unique,
# JSON) — modifiable depuis l'engrenage de la section « À surveiller »
# de la fiche immeuble (retour Phil 2026-07-14 : « une place pour jouer
# avec les alertes »).

_ALERTES_KEY = "immo.alertes_surveiller"

_ALERTES_DEFAUTS: dict = {
    # Bail actif qui échoit dans moins de N jours.
    "bail_fin_enabled": True,
    "bail_fin_jours": 90,
    # Terme hypothécaire qui se termine dans moins de N mois.
    "terme_hypo_enabled": True,
    "terme_hypo_mois": 6,
}


class AlertesConfig(BaseModel):
    bail_fin_enabled: bool = True
    bail_fin_jours: int = Field(default=90, ge=1, le=730)
    terme_hypo_enabled: bool = True
    terme_hypo_mois: int = Field(default=6, ge=1, le=36)


@router.get("/alertes-config", response_model=AlertesConfig)
async def get_alertes_config(db: DBSession, user: CurrentUser) -> AlertesConfig:
    _require_volet(user)
    from app.services.automation_state import get_automation_config

    cfg = await get_automation_config(_ALERTES_KEY)
    merged = {**_ALERTES_DEFAUTS, **cfg}
    try:
        return AlertesConfig(**merged)
    except Exception:  # noqa: BLE001 — config corrompue → défauts
        return AlertesConfig()


@router.put("/alertes-config", response_model=AlertesConfig)
async def put_alertes_config(
    payload: AlertesConfig, db: DBSession, user: CurrentUser
) -> AlertesConfig:
    _require_volet(user)
    from app.services.automation_state import set_automation_config

    await set_automation_config(
        db, _ALERTES_KEY, payload.model_dump(), user_id=user.id
    )
    await db.commit()
    return payload


# ── Immeubles : liste + KPIs agrégés ────────────────────────────────────


@router.get("/immeubles/diagnostic", response_model=List[dict])
async def immeubles_diagnostic(db: DBSession, user: CurrentUser) -> List[dict]:
    """Diagnostic anti-doublons (admin) : TOUS les immeubles avec leur
    nombre de logements / baux et leur scope (entreprise / deal / global).
    Permet d'identifier les vrais doublons (ex. deux « Elgin ») avant toute
    fusion/suppression — un immeuble sans logement ni bail créé sans adresse
    via un picker de tâche est typiquement le doublon à nettoyer.
    """
    _require_volet(user)
    if not user.has_min_role("admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Diagnostic réservé aux administrateurs.",
        )
    immeubles = (
        await db.execute(select(Immeuble).order_by(Immeuble.name.asc()))
    ).scalars().all()
    if not immeubles:
        return []
    ids = [i.id for i in immeubles]

    log_counts = dict(
        (
            await db.execute(
                select(Logement.immeuble_id, func.count(Logement.id))
                .where(Logement.immeuble_id.in_(ids))
                .group_by(Logement.immeuble_id)
            )
        ).all()
    )
    bail_counts = dict(
        (
            await db.execute(
                select(Logement.immeuble_id, func.count(Bail.id))
                .join(Bail, Bail.logement_id == Logement.id)
                .where(Logement.immeuble_id.in_(ids))
                .group_by(Logement.immeuble_id)
            )
        ).all()
    )

    # Compte les occurrences par nom normalisé pour signaler les doublons.
    from collections import Counter

    name_counts = Counter((i.name or "").strip().lower() for i in immeubles)

    out: List[dict] = []
    for i in immeubles:
        scope = (
            "entreprise"
            if i.owner_entreprise_id
            else ("deal" if i.owner_deal_id else "global")
        )
        out.append(
            {
                "id": i.id,
                "name": i.name,
                "address": i.address,
                "city": i.city,
                "scope": scope,
                "owner_entreprise_id": i.owner_entreprise_id,
                "owner_deal_id": i.owner_deal_id,
                "nb_logements": int(log_counts.get(i.id, 0)),
                "nb_baux": int(bail_counts.get(i.id, 0)),
                "is_duplicate_name": name_counts[(i.name or "").strip().lower()]
                > 1,
                "is_active": i.is_active,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
        )
    return out


@router.get("/immeubles/picker", response_model=List[dict])
async def immeubles_picker(
    db: DBSession,
    _: CurrentUser,
    entreprise_id: Optional[int] = None,
    deal_id: Optional[int] = None,
) -> List[dict]:
    """Liste minimale des immeubles actifs pour les pickers de tâches.

    Le catalogue est **scopé** : un immeuble créé depuis la fiche
    d'une entreprise n'apparaît que dans le picker de cette
    entreprise ; idem pour un deal Pipeline. Ce contexte est passé en
    query string. Sans scope → uniquement les immeubles globaux
    (ni entreprise ni deal) — comportement legacy pour les pickers
    qui n'envoient pas de scope.
    """
    q = (
        select(Immeuble.id, Immeuble.name, Immeuble.address)
        .where(Immeuble.is_active.is_(True))
        .order_by(Immeuble.name.asc())
    )
    if entreprise_id is not None:
        q = q.where(Immeuble.owner_entreprise_id == int(entreprise_id))
    elif deal_id is not None:
        q = q.where(Immeuble.owner_deal_id == int(deal_id))
    else:
        q = q.where(
            Immeuble.owner_entreprise_id.is_(None),
            Immeuble.owner_deal_id.is_(None),
        )

    rows = (await db.execute(q)).all()
    return [
        {"id": int(r[0]), "name": r[1], "address": r[2]} for r in rows
    ]


class _ImmeublePickerCreate(BaseModel):
    """Payload léger pour créer un immeuble depuis un picker de tâche.
    Le but est juste d'enrichir le catalogue des immeubles disponibles
    pour les rattacher aux tâches — pas un CRUD complet (qui reste sur
    /immeubles avec garde de volet)."""

    name: str = Field(..., min_length=1, max_length=255)
    # Adresse optionnelle — le picker des tâches ne la demande pas.
    # Si elle n'est pas fournie, on retombe sur le nom comme adresse
    # affichable (et la colonne `address` côté DB reste NOT NULL).
    address: Optional[str] = Field(default=None, max_length=500)
    # Scope (au plus l'un des deux) — restreint la visibilité du
    # nouvel immeuble à l'entreprise ou au deal cible.
    entreprise_id: Optional[int] = Field(default=None, gt=0)
    deal_id: Optional[int] = Field(default=None, gt=0)


@router.post(
    "/immeubles/picker",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
async def immeubles_picker_create(
    body: _ImmeublePickerCreate,
    db: DBSession,
    _: CurrentUser,
) -> dict:
    """Création rapide d'un immeuble depuis le picker des tâches.
    Pas de garde de volet : tout user authentifié peut enrichir le
    catalogue. Si `entreprise_id` ou `deal_id` est fourni, l'immeuble
    n'est visible que dans ce contexte."""
    name = body.name.strip()
    address = (body.address or "").strip() or name
    obj = Immeuble(
        name=name,
        address=address,
        is_active=True,
        owner_entreprise_id=body.entreprise_id,
        owner_deal_id=(
            body.deal_id if body.entreprise_id is None else None
        ),
    )
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    await db.flush()

    return {"id": int(obj.id), "name": obj.name, "address": obj.address}


@router.delete(
    "/immeubles/picker/{immeuble_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def immeubles_picker_delete(
    immeuble_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    """Retire un immeuble du catalogue (soft delete = is_active=False)
    pour qu'il disparaisse des pickers tout en préservant l'historique
    si jamais il est référencé ailleurs. Idempotent."""
    obj = (
        await db.execute(
            select(Immeuble).where(Immeuble.id == immeuble_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        # Idempotent : pas trouvé = on considère que c'est déjà supprimé.
        return
    obj.is_active = False
    obj.updated_at = _now()
    await db.flush()


@router.get("/immeubles", response_model=List[ImmeubleListItem])
async def list_immeubles(
    db: DBSession,
    user: CurrentUser,
    only_active: bool = True,
    entreprise_id: Optional[int] = None,
) -> List[ImmeubleListItem]:
    """Liste des immeubles. Si `entreprise_id` est fourni, filtre sur
    ceux dont l'entreprise est propriétaire (au moins une ImmeubleOwnership).
    """
    _require_volet(user)
    visible = await visible_immeuble_ids(db, user)
    q = select(Immeuble).order_by(Immeuble.name.asc())
    if visible is not None:
        # Employé : limité aux immeubles affectés (set possiblement vide).
        q = q.where(Immeuble.id.in_(visible))
    if only_active:
        q = q.where(Immeuble.is_active.is_(True))
    if entreprise_id is not None:
        q = q.join(
            ImmeubleOwnership,
            ImmeubleOwnership.immeuble_id == Immeuble.id,
        ).where(ImmeubleOwnership.entreprise_id == entreprise_id)
    immeubles = (await db.execute(q)).scalars().all()
    if not immeubles:
        return []

    # Aggrégats logements par immeuble
    log_rows = (
        await db.execute(
            select(
                Logement.immeuble_id,
                Logement.status,
                func.count(Logement.id),
            )
            .where(Logement.immeuble_id.in_([i.id for i in immeubles]))
            .group_by(Logement.immeuble_id, Logement.status)
        )
    ).all()
    logs_by_imm: dict[int, dict[str, int]] = {}
    for imm_id, st, n in log_rows:
        logs_by_imm.setdefault(imm_id, {})[st] = int(n)

    # Revenu mensuel = somme baux actifs des logements de l'immeuble
    bail_rows = (
        await db.execute(
            select(
                Logement.immeuble_id,
                func.coalesce(func.sum(Bail.loyer_mensuel), 0),
            )
            .join(Bail, Bail.logement_id == Logement.id)
            .where(
                and_(
                    Logement.immeuble_id.in_([i.id for i in immeubles]),
                    Bail.status == BailStatus.ACTIF.value,
                )
            )
            .group_by(Logement.immeuble_id)
        )
    ).all()
    rev_by_imm = {r[0]: float(r[1] or 0) for r in bail_rows}

    out: List[ImmeubleListItem] = []
    for imm in immeubles:
        sts = logs_by_imm.get(imm.id, {})
        nb_actifs = sum(
            n for st, n in sts.items()
            if st != LogementStatus.HORS_LOC.value
        )
        nb_occ = sts.get(LogementStatus.OCCUPE.value, 0)
        revenu = rev_by_imm.get(imm.id, 0.0)
        taux = (nb_occ / nb_actifs) if nb_actifs > 0 else 0.0
        out.append(
            ImmeubleListItem(
                id=imm.id,
                name=imm.name,
                address=imm.address,
                city=imm.city,
                type=imm.type,
                nb_logements=imm.nb_logements,
                cover_photo_url=imm.cover_photo_url,
                has_cover_photo=bool(imm.cover_photo_content_type),
                is_active=imm.is_active,
                nb_logements_actifs=nb_actifs,
                nb_logements_occupes=nb_occ,
                revenu_mensuel=round(revenu, 2),
                taux_occupation=round(taux, 4),
            )
        )
    return out


@router.post(
    "/immeubles",
    response_model=ImmeubleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_immeuble(
    payload: ImmeubleCreate, db: DBSession, user: CurrentUser
) -> ImmeubleRead:
    _require_volet(user)
    data = payload.model_dump()
    # Champ optionnel non persisté sur Immeuble : on l'extrait avant.
    auto_entreprise_id = data.pop("entreprise_id", None)
    # Nom optionnel : si l'utilisateur n'en fournit pas, on prend l'adresse
    # complète comme nom affichable (cas usuel : un immeuble = une adresse).
    if not data.get("name") or not str(data["name"]).strip():
        addr = data.get("address") or ""
        city = data.get("city")
        data["name"] = f"{addr}, {city}" if city else addr
    obj = Immeuble(**data)
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    await db.flush()  # pour obtenir obj.id avant de créer l'ownership

    # Auto-rattache à l'entreprise active à 100 % si fourni.
    if auto_entreprise_id:
        ownership = ImmeubleOwnership(
            immeuble_id=obj.id,
            entreprise_id=auto_entreprise_id,
            ownership_pct=100.0,
        )
        db.add(ownership)

    await db.commit()
    await db.refresh(obj)
    return _immeuble_to_read(obj)


# ── Upload + stream cover photo ────────────────────────────────────────


_PHOTO_MIME_ALLOWED = {
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
}
_PHOTO_MAX_BYTES = 8 * 1024 * 1024  # 8 Mo


@router.post(
    "/immeubles/{immeuble_id}/cover-photo",
    response_model=ImmeubleRead,
)
async def upload_cover_photo(
    immeuble_id: int,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> ImmeubleRead:
    _require_volet(user)
    obj = await _get_immeuble_or_404(db, immeuble_id)
    ct = (file.content_type or "").lower()
    if ct not in _PHOTO_MIME_ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Format non supporté (JPG, PNG, WEBP, HEIC).",
        )
    blob = await file.read()
    if not blob:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Fichier vide."
        )
    if len(blob) > _PHOTO_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Fichier trop gros (> {_PHOTO_MAX_BYTES // (1024*1024)} Mo).",
        )
    obj.cover_photo_blob = blob
    obj.cover_photo_content_type = ct
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return _immeuble_to_read(obj)


async def _resolve_user_for_image(
    request: Request, db, t: Optional[str]
):
    """Lit le JWT depuis le header Authorization OU le query `?t=`,
    valide et retourne l'utilisateur. Permet d'utiliser ces URL dans
    `<img src>` qui ne porte pas de header personnalisé.
    """
    token = t
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1]
    if not token:
        raise HTTPException(401, "Token manquant.")
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(401, "Token invalide.")
    user = await UserRepository(db).get_by_id(int(user_id))
    if user is None:
        raise HTTPException(401, "Utilisateur introuvable.")
    return user


@router_images.get("/immeubles/{immeuble_id}/cover-photo")
async def stream_cover_photo(
    immeuble_id: int,
    db: DBSession,
    request: Request,
    t: Optional[str] = Query(default=None),
) -> Response:
    user = await _resolve_user_for_image(request, db, t)
    _require_volet(user)
    obj = await _get_immeuble_or_404(db, immeuble_id)
    # Force-load le blob deferred.
    await db.refresh(obj, attribute_names=["cover_photo_blob"])
    if not obj.cover_photo_blob:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune photo de couverture.",
        )
    ct = obj.cover_photo_content_type or "application/octet-stream"
    return Response(
        content=bytes(obj.cover_photo_blob),
        media_type=ct,
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": f'inline; filename="cover-{immeuble_id}.{ct.split("/")[-1] or "bin"}"',
        },
    )


@router.delete(
    "/immeubles/{immeuble_id}/cover-photo",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_cover_photo(
    immeuble_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await _get_immeuble_or_404(db, immeuble_id)
    obj.cover_photo_blob = None
    obj.cover_photo_content_type = None
    obj.updated_at = _now()
    await db.commit()


@router.get("/immeubles/{immeuble_id}", response_model=ImmeubleRead)
async def get_immeuble(
    immeuble_id: int, db: DBSession, user: CurrentUser
) -> ImmeubleRead:
    _require_volet(user)
    await _require_immeuble_visible(db, user, immeuble_id)
    obj = await _get_immeuble_or_404(db, immeuble_id)
    return _immeuble_to_read(obj)


@router.patch("/immeubles/{immeuble_id}", response_model=ImmeubleRead)
async def update_immeuble(
    immeuble_id: int,
    payload: ImmeubleUpdate,
    db: DBSession,
    user: CurrentUser,
) -> ImmeubleRead:
    _require_volet(user)
    obj = await _get_immeuble_or_404(db, immeuble_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return _immeuble_to_read(obj)


@router.delete(
    "/immeubles/{immeuble_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_immeuble(
    immeuble_id: int,
    db: DBSession,
    user: Annotated[User, Depends(require_capability("immeuble.delete"))],
) -> None:
    _require_volet(user)
    obj = await _get_immeuble_or_404(db, immeuble_id)
    await db.delete(obj)
    await db.commit()


# ── Ownership ──────────────────────────────────────────────────────────


@router.get(
    "/immeubles/{immeuble_id}/ownerships",
    response_model=List[ImmeubleOwnershipRead],
)
async def list_ownerships(
    immeuble_id: int, db: DBSession, user: CurrentUser
) -> List[ImmeubleOwnershipRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(ImmeubleOwnership).where(
                ImmeubleOwnership.immeuble_id == immeuble_id
            )
        )
    ).scalars().all()
    return [ImmeubleOwnershipRead.model_validate(r) for r in rows]


@router.post(
    "/immeubles/{immeuble_id}/ownerships",
    response_model=ImmeubleOwnershipRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_ownership(
    immeuble_id: int,
    payload: ImmeubleOwnershipCreate,
    db: DBSession,
    user: CurrentUser,
) -> ImmeubleOwnershipRead:
    _require_volet(user)
    await _get_immeuble_or_404(db, immeuble_id)
    obj = ImmeubleOwnership(
        immeuble_id=immeuble_id,
        entreprise_id=payload.entreprise_id,
        ownership_pct=payload.ownership_pct,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return ImmeubleOwnershipRead.model_validate(obj)


@router.delete(
    "/ownerships/{ownership_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_ownership(
    ownership_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(ImmeubleOwnership, ownership_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Ownership introuvable.")
    await db.delete(obj)
    await db.commit()


class _SetOwnerRequest(BaseModel):
    entreprise_id: int


@router.put(
    "/immeubles/{immeuble_id}/owner",
    response_model=List[ImmeubleOwnershipRead],
)
async def set_immeuble_owner(
    immeuble_id: int,
    payload: _SetOwnerRequest,
    db: DBSession,
    user: CurrentUser,
) -> List[ImmeubleOwnershipRead]:
    """Réassigne l'immeuble à UNE entreprise propriétaire à 100 %.

    Remplace toutes les ownerships existantes par une seule (cas usuel :
    corriger la compagnie propriétaire d'un immeuble). Atomique."""
    _require_volet(user)
    await _get_immeuble_or_404(db, immeuble_id)
    ent = await db.get(Entreprise, payload.entreprise_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Entreprise introuvable.")
    existing = (
        await db.execute(
            select(ImmeubleOwnership).where(
                ImmeubleOwnership.immeuble_id == immeuble_id
            )
        )
    ).scalars().all()
    for o in existing:
        await db.delete(o)
    fresh = ImmeubleOwnership(
        immeuble_id=immeuble_id,
        entreprise_id=payload.entreprise_id,
        ownership_pct=100.0,
    )
    db.add(fresh)
    await db.commit()
    await db.refresh(fresh)
    return [ImmeubleOwnershipRead.model_validate(fresh)]


# ── Bon de travail (réparation → volet Construction) ───────────────────


class _BonFromImmeubleRequest(BaseModel):
    titre: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    logement: Optional[str] = None  # n° de logement (affichage, legacy)
    logement_id: Optional[int] = None  # FK logement concerné (optionnel)
    # Urgence posée dès la création (comme côté Construction) : le bon
    # remonte en haut des kanbans des deux pôles.
    is_urgent: bool = False


@router.post("/immeubles/{immeuble_id}/bon-travail")
async def create_bon_from_immeuble(
    immeuble_id: int,
    payload: _BonFromImmeubleRequest,
    db: DBSession,
    user: CurrentUser,
) -> dict:
    """Crée un bon de travail (volet Construction) pour une réparation sur
    cet immeuble. Convertit au passage la compagnie propriétaire en client
    si elle n'en est pas déjà un. Le bon est créé en brouillon — un
    responsable construction le reprend ensuite (estimé, envoi, signature,
    conversion en projet/facture)."""
    _require_volet(user)
    imm = await _get_immeuble_or_404(db, immeuble_id)

    own = (
        await db.execute(
            select(ImmeubleOwnership).where(
                ImmeubleOwnership.immeuble_id == immeuble_id
            )
        )
    ).scalars().first()
    ent = await db.get(Entreprise, own.entreprise_id) if own else None

    client = None
    client_created = False
    if ent is not None:
        client = (
            await db.execute(
                select(Client).where(
                    func.lower(Client.name) == ent.name.strip().lower()
                )
            )
        ).scalars().first()
        if client is None:
            client = Client(
                name=ent.name,
                is_company=True,
                address=imm.address,
                language="fr",
            )
            db.add(client)
            await db.flush()
            client_created = True

    loc_label = payload.logement
    if payload.logement_id and not loc_label:
        lg = await db.get(Logement, payload.logement_id)
        loc_label = lg.numero if lg else None
    loc = f" — logement {loc_label}" if loc_label else ""
    where = f"{imm.address}{(', ' + imm.city) if imm.city else ''}"
    scope = (
        f"Immeuble : {imm.name}{loc}\n"
        f"Adresse : {where}\n"
        "Source : Gestion immobilière (réparation)."
    )
    # Référence auto anti-collision : même motif visible BON-AAAAMMJJ-HHMMSS,
    # mais via le helper partagé (suffixe -N si la seconde est déjà prise) pour
    # ne plus risquer un 500 sur la contrainte UNIQUE. Cf. business.py.
    from app.api.v1.endpoints.business import generate_bt_reference

    bon = BonTravail(
        reference=await generate_bt_reference(
            db, prefix="BON-", date_format="%Y%m%d-%H%M%S", now=_now()
        ),
        title=payload.titre,
        description=payload.description,
        scope_md=scope,
        client_id=client.id if client else None,
        address=f"{where}{loc}",
        status="draft",
        origin="gestion_immo",
        # Bon INTERNE (entretien de nos immeubles) : rattachement complet,
        # aucune signature. Apparaît sur le board Construction ET le miroir
        # Gestion locative.
        kind="interne",
        # Créé côté Gestion locative : l'exécutant (nos hommes vs
        # sous-traitant) n'est PAS encore décidé → "à classifier". Le
        # gestionnaire Construction tranchera depuis la fiche du bon.
        executant_type="a_classifier",
        owner_entreprise_id=own.entreprise_id if own else None,
        immeuble_id=immeuble_id,
        logement_id=payload.logement_id,
        marge_pct=10,
        requires_signature=False,
        is_urgent=bool(payload.is_urgent),
    )
    bon.created_at = _now()
    bon.updated_at = _now()
    db.add(bon)
    await db.flush()
    # Notifie les gestionnaires (manager+) — comme côté Construction.
    from app.services.notifications import notify_role

    await notify_role(
        db,
        min_role="manager",
        kind="bon_travail",
        title="Nouveau bon de travail — " + (bon.address or bon.reference),
        body=bon.title,
        href=f"/app/bons/{bon.id}",
    )
    await db.commit()
    await db.refresh(bon)
    return {
        "bon_id": bon.id,
        "reference": bon.reference,
        "client_id": client.id if client else None,
        "client_name": ent.name if ent else None,
        "client_created": client_created,
    }


# ── Miroir lecture seule des bons de travail (gestion immobilière) ─────
#
# Kyle (volet immobilier) crée des bons de travail qui partent en
# Construction. Il doit pouvoir SUIVRE leur avancement depuis sa zone,
# sans pouvoir assigner de personnes ni modifier la planification (ça reste
# du ressort de Construction). Ces deux endpoints servent un miroir en
# lecture seule, gardé par `_require_volet` (immobilier).


def _project_status_progress(status_value: Optional[str]) -> int:
    """Pourcentage indicatif d'avancement à partir du statut projet."""
    return {
        "planned": 5,
        "ready_to_start": 15,
        "in_progress": 60,
        "suspended": 40,
        "delivered": 100,
    }.get(status_value or "", 0)


class _BonAvancementProject(BaseModel):
    id: int
    label: str
    status: Optional[str]
    progress_pct: int
    start_date: Optional[date]
    end_date: Optional[date]
    phase_count: int


class _BonAvancementItem(BaseModel):
    id: int
    reference: str
    title: str
    status: str
    created_at: Optional[datetime]
    sent_at: Optional[datetime]
    signed_at: Optional[datetime]
    client_name: Optional[str]
    project: Optional[_BonAvancementProject]
    address: Optional[str] = None
    amount: Optional[float] = None
    immeuble_id: Optional[int] = None
    logement_id: Optional[int] = None
    is_urgent: bool = False


@router.get("/bons-travail", response_model=List[_BonAvancementItem])
async def list_gestion_immo_bons(db: DBSession, user: CurrentUser) -> List[_BonAvancementItem]:
    """Liste TOUS les bons de travail issus de la gestion immobilière, avec
    leur avancement (statut du bon + état du chantier lié). Lecture seule."""
    _require_volet(user)
    bons = (
        await db.execute(
            select(BonTravail)
            .where(
                (BonTravail.kind == "interne")
                | (BonTravail.origin == "gestion_immo")
                | (BonTravail.scope_md.ilike("%Gestion immobilière%"))
            )
            .order_by(BonTravail.created_at.desc())
        )
    ).scalars().all()
    if not bons:
        return []

    client_ids = {b.client_id for b in bons if b.client_id}
    clients = {
        c.id: c.name
        for c in (
            await db.execute(select(Client).where(Client.id.in_(client_ids)))
        ).scalars().all()
    } if client_ids else {}

    project_ids = {b.project_id for b in bons if b.project_id}
    projects = {
        p.id: p
        for p in (
            await db.execute(select(Project).where(Project.id.in_(project_ids)))
        ).scalars().all()
    } if project_ids else {}

    phase_counts: dict[int, int] = {}
    if project_ids:
        rows = (
            await db.execute(
                select(ProjectPhase.project_id, func.count(ProjectPhase.id))
                .where(ProjectPhase.project_id.in_(project_ids))
                .group_by(ProjectPhase.project_id)
            )
        ).all()
        phase_counts = {pid: int(cnt) for pid, cnt in rows}

    out: List[_BonAvancementItem] = []
    for b in bons:
        proj_summary = None
        proj = projects.get(b.project_id) if b.project_id else None
        if proj is not None:
            proj_summary = _BonAvancementProject(
                id=proj.id,
                label=(proj.address or proj.name or f"Projet #{proj.id}"),
                status=proj.status,
                progress_pct=_project_status_progress(proj.status),
                start_date=proj.start_date,
                end_date=proj.end_date,
                phase_count=phase_counts.get(proj.id, 0),
            )
        out.append(
            _BonAvancementItem(
                id=b.id,
                reference=b.reference,
                title=b.title,
                status=b.status,
                created_at=b.created_at,
                sent_at=b.sent_at,
                signed_at=b.signed_at,
                client_name=clients.get(b.client_id) if b.client_id else None,
                project=proj_summary,
                address=b.address,
                amount=float(b.amount) if b.amount is not None else None,
                immeuble_id=b.immeuble_id,
                logement_id=b.logement_id,
                is_urgent=bool(getattr(b, "is_urgent", False)),
            )
        )
    return out


# ── Roll-up des dépenses de maintenance (sans profit) ─────────────────────
class _RollupLogement(BaseModel):
    logement_id: Optional[int]
    numero: Optional[str]
    total: float
    count: int


class _RollupImmeuble(BaseModel):
    immeuble_id: int
    name: str
    address: Optional[str]
    total: float
    count: int
    communs_total: float
    communs_count: int = 0
    logements: List[_RollupLogement]


@router.get("/maintenance-rollup", response_model=List[_RollupImmeuble])
async def maintenance_rollup(
    db: DBSession,
    user: CurrentUser,
    year: Optional[int] = None,
    immeuble_id: Optional[int] = None,
) -> List[_RollupImmeuble]:
    """Dépenses de maintenance ($/an) par immeuble puis par appartement.

    Somme le montant refacturé des bons internes non annulés de l'année.
    Aucune notion de profit (vue propriétaire/locatif). Filtrable sur un
    immeuble précis (pour sa fiche)."""
    _require_volet(user)
    target_year = year if year is not None else _now().year
    # Fenêtre de l'année ciblée bornée en SQL plutôt que filtrée en Python
    # après un fetch complet (évite de charger tous les bons internes de
    # l'historique). created_at est un TIMESTAMPTZ stocké en UTC : on utilise
    # des bornes datetime UTC (minuit 1er janvier ← inclus, minuit 1er janvier
    # suivant → exclu) pour reproduire exactement `created_at.year == year`
    # quelle que soit la timezone de session Postgres. NULL reste exclu par la
    # comparaison (created_at est de toute façon NOT NULL).
    year_start = datetime(target_year, 1, 1, tzinfo=timezone.utc)
    year_end = datetime(target_year + 1, 1, 1, tzinfo=timezone.utc)
    q = select(BonTravail).where(
        BonTravail.kind == "interne",
        BonTravail.status != "cancelled",
        BonTravail.immeuble_id.isnot(None),
        BonTravail.created_at >= year_start,
        BonTravail.created_at < year_end,
    )
    if immeuble_id is not None:
        q = q.where(BonTravail.immeuble_id == int(immeuble_id))
    bons = (await db.execute(q)).scalars().all()
    if not bons:
        return []

    imm_ids = {b.immeuble_id for b in bons}
    immeubles = {
        i.id: i
        for i in (
            await db.execute(select(Immeuble).where(Immeuble.id.in_(imm_ids)))
        ).scalars().all()
    }
    log_ids = {b.logement_id for b in bons if b.logement_id}
    logements = (
        {
            lg.id: lg
            for lg in (
                await db.execute(
                    select(Logement).where(Logement.id.in_(log_ids))
                )
            ).scalars().all()
        }
        if log_ids
        else {}
    )

    by_imm: dict = {}
    for b in bons:
        amt = float(b.amount) if b.amount is not None else 0.0
        e = by_imm.setdefault(
            b.immeuble_id,
            {
                "total": 0.0,
                "count": 0,
                "communs": 0.0,
                "communs_count": 0,
                "logs": {},
            },
        )
        e["total"] += amt
        e["count"] += 1
        if b.logement_id:
            le = e["logs"].setdefault(
                b.logement_id, {"total": 0.0, "count": 0}
            )
            le["total"] += amt
            le["count"] += 1
        else:
            e["communs"] += amt
            e["communs_count"] += 1

    out: List[_RollupImmeuble] = []
    for imm_id, e in by_imm.items():
        imm = immeubles.get(imm_id)
        out.append(
            _RollupImmeuble(
                immeuble_id=imm_id,
                name=imm.name if imm else f"Immeuble #{imm_id}",
                address=imm.address if imm else None,
                total=round(e["total"], 2),
                count=e["count"],
                communs_total=round(e["communs"], 2),
                communs_count=int(e["communs_count"]),
                logements=[
                    _RollupLogement(
                        logement_id=lid,
                        numero=(
                            logements[lid].numero if lid in logements else None
                        ),
                        total=round(lv["total"], 2),
                        count=lv["count"],
                    )
                    for lid, lv in sorted(e["logs"].items())
                ],
            )
        )
    out.sort(key=lambda x: x.total, reverse=True)
    return out


class _BonDemandeEdit(BaseModel):
    titre: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    is_urgent: Optional[bool] = None
    immeuble_id: Optional[int] = None
    logement_id: Optional[int] = None
    # Sentinelle : True = mettre logement_id à NULL (communs / immeuble entier).
    clear_logement: Optional[bool] = None


@router.patch("/bons-travail/{bon_id}/demande")
async def edit_gestion_immo_bon_demande(
    bon_id: int, payload: _BonDemandeEdit, db: DBSession, user: CurrentUser
) -> dict:
    """Le volet locatif peut corriger la DEMANDE d'un bon interne s'il a fait
    une erreur : titre, description, immeuble, appartement, urgence — pas la
    planification ni la refacturation (réservées à Construction)."""
    _require_volet(user)
    bon = await db.get(BonTravail, bon_id)
    if bon is None or (bon.kind or "construction") != "interne":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bon introuvable")
    if payload.titre is not None:
        bon.title = payload.titre.strip()
    if payload.description is not None:
        bon.description = payload.description or None
    if payload.is_urgent is not None:
        bon.is_urgent = bool(payload.is_urgent)
    if payload.immeuble_id is not None:
        bon.immeuble_id = payload.immeuble_id
        imm = await db.get(Immeuble, payload.immeuble_id)
        if imm is not None:
            # Recale le propriétaire depuis l'ownership de l'immeuble.
            own = (
                await db.execute(
                    select(ImmeubleOwnership).where(
                        ImmeubleOwnership.immeuble_id == payload.immeuble_id
                    )
                )
            ).scalars().first()
            if own is not None:
                bon.owner_entreprise_id = own.entreprise_id
    if payload.clear_logement:
        bon.logement_id = None
    elif payload.logement_id is not None:
        bon.logement_id = payload.logement_id
    # Recompose l'adresse d'affichage (immeuble · appartement).
    imm2 = (
        await db.get(Immeuble, bon.immeuble_id) if bon.immeuble_id else None
    )
    if imm2 is not None:
        base = imm2.address or imm2.name
        if bon.logement_id:
            lg = await db.get(Logement, bon.logement_id)
            bon.address = (
                f"{base} · App {lg.numero}" if lg else base
            )
        else:
            bon.address = f"{base} · Communs / immeuble entier"
    bon.updated_at = _now()
    await db.commit()
    return {"ok": True}


class _BonPhaseRead(BaseModel):
    id: int
    name: str
    start_date: Optional[date]
    end_date: Optional[date]
    duration_days: Optional[float]
    assignee_name: Optional[str]


class _BonPhotoMeta(BaseModel):
    id: int
    caption: Optional[str]
    content_type: str


class _BonAvancementDetail(BaseModel):
    id: int
    reference: str
    title: str
    description: Optional[str]
    scope_md: Optional[str]
    status: str
    created_at: Optional[datetime]
    sent_at: Optional[datetime]
    signed_at: Optional[datetime]
    client_name: Optional[str]
    project: Optional[_BonAvancementProject]
    phases: List[_BonPhaseRead]
    photos: List[_BonPhotoMeta]
    # Notes de l'exécutant — lecture seule côté locatif.
    work_notes: Optional[str] = None
    address: Optional[str] = None
    is_urgent: bool = False
    immeuble_id: Optional[int] = None
    logement_id: Optional[int] = None


@router.get("/bons-travail/{bon_id}", response_model=_BonAvancementDetail)
async def get_gestion_immo_bon(
    bon_id: int, db: DBSession, user: CurrentUser
) -> _BonAvancementDetail:
    """Détail lecture seule d'un bon de travail gestion immobilière :
    statut + planification du chantier lié (phases, dates, personnes
    assignées affichées mais NON modifiables)."""
    _require_volet(user)
    bon = await db.get(BonTravail, bon_id)
    if bon is None or not (
        (bon.kind or "construction") == "interne"
        or bon.origin == "gestion_immo"
        or (bon.scope_md and "Gestion immobilière" in bon.scope_md)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bon de travail introuvable.",
        )

    client_name = None
    if bon.client_id:
        c = await db.get(Client, bon.client_id)
        client_name = c.name if c else None

    proj_summary = None
    phases_out: List[_BonPhaseRead] = []
    photos_out: List[_BonPhotoMeta] = []
    if bon.project_id:
        proj = await db.get(Project, bon.project_id)
        if proj is not None:
            phases = (
                await db.execute(
                    select(ProjectPhase)
                    .where(ProjectPhase.project_id == proj.id)
                    .order_by(ProjectPhase.position.asc(), ProjectPhase.id.asc())
                )
            ).scalars().all()
            proj_summary = _BonAvancementProject(
                id=proj.id,
                label=(proj.address or proj.name or f"Projet #{proj.id}"),
                status=proj.status,
                progress_pct=_project_status_progress(proj.status),
                start_date=proj.start_date,
                end_date=proj.end_date,
                phase_count=len(phases),
            )
            # Pré-charge les noms des personnes assignées (employés + ST).
            emp_ids = {p.assignee_employe_id for p in phases if p.assignee_employe_id}
            st_ids = {
                p.assignee_sous_traitant_id for p in phases if p.assignee_sous_traitant_id
            }
            emps = {
                e.id: e.full_name
                for e in (
                    await db.execute(select(Employe).where(Employe.id.in_(emp_ids)))
                ).scalars().all()
            } if emp_ids else {}
            sts = {
                s.id: s.full_name
                for s in (
                    await db.execute(
                        select(SousTraitant).where(SousTraitant.id.in_(st_ids))
                    )
                ).scalars().all()
            } if st_ids else {}
            for p in phases:
                end_d = None
                if p.start_date is not None and p.duration_days:
                    span = max(int(p.duration_days) - 1, 0)
                    end_d = p.start_date + timedelta(days=span)
                assignee = None
                if p.assignee_employe_id:
                    assignee = emps.get(p.assignee_employe_id)
                elif p.assignee_sous_traitant_id:
                    assignee = sts.get(p.assignee_sous_traitant_id)
                phases_out.append(
                    _BonPhaseRead(
                        id=p.id,
                        name=p.name,
                        start_date=p.start_date,
                        end_date=end_d,
                        duration_days=float(p.duration_days) if p.duration_days else None,
                        assignee_name=assignee,
                    )
                )

            # Métadonnées des photos du chantier (sans charger les blobs).
            prows = (
                await db.execute(
                    select(
                        ProjectPhoto.id,
                        ProjectPhoto.caption,
                        ProjectPhoto.content_type,
                    )
                    .where(ProjectPhoto.project_id == proj.id)
                    .order_by(ProjectPhoto.created_at.desc())
                )
            ).all()
            photos_out = [
                _BonPhotoMeta(id=pid, caption=cap, content_type=ct)
                for pid, cap, ct in prows
            ]

    return _BonAvancementDetail(
        id=bon.id,
        reference=bon.reference,
        title=bon.title,
        description=bon.description,
        scope_md=bon.scope_md,
        status=bon.status,
        created_at=bon.created_at,
        sent_at=bon.sent_at,
        signed_at=bon.signed_at,
        client_name=client_name,
        project=proj_summary,
        phases=phases_out,
        photos=photos_out,
        work_notes=bon.work_notes,
        address=bon.address,
        is_urgent=bool(getattr(bon, "is_urgent", False)),
        immeuble_id=bon.immeuble_id,
        logement_id=bon.logement_id,
    )


@router.get("/bons-travail/{bon_id}/photos/{photo_id}")
async def get_gestion_immo_bon_photo(
    bon_id: int, photo_id: int, db: DBSession, user: CurrentUser
) -> Response:
    """Sert l'image d'une photo de chantier, pour un bon gestion immobilière.
    Passe par la porte immobilier : Kyle (sans volet construction) peut voir
    les photos d'avancement du chantier lié à SON bon, en lecture seule."""
    _require_volet(user)
    bon = await db.get(BonTravail, bon_id)
    if (
        bon is None
        or bon.project_id is None
        or not (
            (bon.kind or "construction") == "interne"
            or bon.origin == "gestion_immo"
            or (bon.scope_md and "Gestion immobilière" in bon.scope_md)
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bon introuvable."
        )
    # Charge les octets explicitement (la colonne `image` est deferred), en
    # vérifiant que la photo appartient bien au chantier de CE bon.
    row = (
        await db.execute(
            select(ProjectPhoto.image, ProjectPhoto.content_type).where(
                ProjectPhoto.id == photo_id,
                ProjectPhoto.project_id == bon.project_id,
            )
        )
    ).first()
    if row is None or not row[0]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo introuvable."
        )
    return Response(content=bytes(row[0]), media_type=row[1] or "image/jpeg")


@router.post("/bons-travail/{bon_id}/photos")
async def upload_gestion_immo_bon_photo(
    bon_id: int,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> dict:
    """Ajoute une photo (problématique « avant », ou « après ») à un bon de
    travail gestion immobilière. La photo est attachée au PROJET lié (mini-
    projet) ; on le crée à la volée si le bon n'en a pas encore. Accepte
    images + PDF."""
    _require_volet(user)
    bon = await db.get(BonTravail, bon_id)
    if bon is None or not (
        (bon.kind or "construction") == "interne"
        or bon.origin == "gestion_immo"
        or (bon.scope_md and "Gestion immobilière" in bon.scope_md)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bon introuvable."
        )

    ct = (file.content_type or "").lower()
    if ct not in _PHOTO_MIME_ALLOWED and ct != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Format non supporté (JPG, PNG, WEBP, HEIC, PDF).",
        )
    blob = await file.read()
    if not blob:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Fichier vide."
        )
    if len(blob) > _PHOTO_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Fichier trop gros (> {_PHOTO_MAX_BYTES // (1024*1024)} Mo).",
        )

    # Le bon doit avoir un projet pour porter ses photos : on le crée au
    # besoin (mini-projet — cohérent avec « Achats, heures & facture »).
    if bon.project_id is None:
        proj = Project(
            name=bon.title or f"Bon {bon.reference}",
            client_id=bon.client_id,
            kind="bon_travail",
            responsible_user_id=getattr(bon, "assignee_user_id", None),
            status="in_progress",
            address=getattr(bon, "address", None),
        )
        db.add(proj)
        await db.flush()
        bon.project_id = proj.id

    photo = ProjectPhoto(
        project_id=bon.project_id,
        image=blob,
        content_type=ct,
        caption="Problématique (avant)",
        uploaded_by_email=user.email,
    )
    db.add(photo)
    await db.commit()
    await db.refresh(photo)
    return {"photo_id": photo.id, "project_id": bon.project_id}


@router.post("/entreprises/{entreprise_id}/retirer-portefeuille")
async def retirer_entreprise_portefeuille(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> dict:
    """Retire l'entreprise du volet immobilier : supprime uniquement les
    liens de propriété (ImmeubleOwnership) entre cette entreprise et ses
    immeubles. NE touche PAS l'entreprise ni ses tâches côté gestion
    d'entreprise (séparation des volets). Les immeubles eux-mêmes restent
    (sans propriétaire — à réassigner au besoin)."""
    _require_volet(user)
    rows = (
        await db.execute(
            select(ImmeubleOwnership).where(
                ImmeubleOwnership.entreprise_id == entreprise_id
            )
        )
    ).scalars().all()
    for o in rows:
        await db.delete(o)
    await db.commit()
    return {"removed_ownerships": len(rows)}


# ── Signature de bail ──────────────────────────────────────────────────


class _BailSendRequest(BaseModel):
    to: Optional[List[str]] = None  # défaut : courriel du locataire


@router.post("/baux/{bail_id}/send")
async def send_bail(
    bail_id: int,
    payload: _BailSendRequest,
    db: DBSession,
    user: CurrentUser,
) -> dict:
    """Envoie le bail au locataire pour signature électronique (lien
    public). Retourne le statut d'envoi."""
    _require_volet(user)
    from app.services.bail_sign import BailSendError, send_bail_for_signature

    try:
        bail = await send_bail_for_signature(db, bail_id, to=payload.to)
    except BailSendError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    await db.commit()
    return {
        "sent_to": bail.sent_to_email,
        "signature_token": bail.signature_token,
    }


@router.get("/baux/{bail_id}/document")
async def download_bail_document(
    bail_id: int,
    db: DBSession,
    user: CurrentUser,
) -> Response:
    """Telecharge le PDF du bail signe (regenere a la volee).

    Disponible uniquement pour un bail effectivement signe. Independant
    du Drive : la piece reste recuperable depuis Kratos meme si l'immeuble
    n'a pas de Drive lie.
    """
    _require_volet(user)
    bail = await db.get(Bail, bail_id)
    if bail is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Bail introuvable."
        )
    if bail.signed_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Ce bail n'est pas encore signe.",
        )
    from app.services.bail_signed_pdf import render_bail_signed_pdf

    pdf = await render_bail_signed_pdf(db, bail_id)
    if not pdf:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Generation du PDF impossible.",
        )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="Bail_{bail_id}_signe.pdf"'
            )
        },
    )


# ── Logements ──────────────────────────────────────────────────────────


@router.get(
    "/immeubles/{immeuble_id}/logements",
    response_model=List[LogementRead],
)
async def list_logements(
    immeuble_id: int, db: DBSession, user: CurrentUser
) -> List[LogementRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(Logement)
            .where(Logement.immeuble_id == immeuble_id)
            .order_by(Logement.numero.asc())
        )
    ).scalars().all()
    return [LogementRead.model_validate(r) for r in rows]


@router.post(
    "/logements",
    response_model=LogementRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_logement(
    payload: LogementCreate, db: DBSession, user: CurrentUser
) -> LogementRead:
    _require_volet(user)
    await _get_immeuble_or_404(db, payload.immeuble_id)
    obj = Logement(**payload.model_dump())
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return LogementRead.model_validate(obj)


@router.patch("/logements/{logement_id}", response_model=LogementRead)
async def update_logement(
    logement_id: int,
    payload: LogementUpdate,
    db: DBSession,
    user: CurrentUser,
) -> LogementRead:
    _require_volet(user)
    obj = await db.get(Logement, logement_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Logement introuvable.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return LogementRead.model_validate(obj)


@router.delete(
    "/logements/{logement_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_logement(
    logement_id: int,
    db: DBSession,
    user: Annotated[User, Depends(require_capability("logement.delete"))],
) -> None:
    _require_volet(user)
    obj = await db.get(Logement, logement_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Logement introuvable.")
    await db.delete(obj)
    await db.commit()


@router.get(
    "/logements/{logement_id}/dossier", response_model=LogementDossier
)
async def logement_dossier(
    logement_id: int, db: DBSession, user: CurrentUser
) -> LogementDossier:
    """Fiche 360 d'un logement : infos + immeuble, tous ses baux (avec
    locataire, document, signature), les bons de travail rattachés
    (rénos / maintenance) et l'historique de loyer dérivé des baux
    (fluctuation de bail en bail)."""
    _require_volet(user)
    lg = await db.get(Logement, logement_id)
    if lg is None:
        raise HTTPException(status_code=404, detail="Logement introuvable.")
    await _require_immeuble_visible(db, user, lg.immeuble_id)
    imm = await db.get(Immeuble, lg.immeuble_id)

    baux = (
        await db.execute(
            select(Bail)
            .where(Bail.logement_id == logement_id)
            .order_by(Bail.date_debut.desc())
        )
    ).scalars().all()

    loc_ids = {b.locataire_id for b in baux if b.locataire_id}
    loc_by_id = {}
    if loc_ids:
        for loc in (
            await db.execute(
                select(Locataire).where(Locataire.id.in_(list(loc_ids)))
            )
        ).scalars().all():
            loc_by_id[loc.id] = loc

    dossier_baux = []
    for b in baux:
        loc = loc_by_id.get(b.locataire_id)
        dossier_baux.append(
            LogementDossierBail(
                id=b.id,
                locataire=(
                    LogementDossierLocataire(
                        id=loc.id, full_name=loc.full_name
                    )
                    if loc is not None
                    else None
                ),
                loyer_mensuel=float(b.loyer_mensuel or 0),
                date_debut=b.date_debut,
                date_fin=b.date_fin,
                status=b.status,
                document_url=b.document_url,
                signed_at=b.signed_at,
            )
        )

    bons = (
        await db.execute(
            select(BonTravail)
            .where(BonTravail.logement_id == logement_id)
            .order_by(BonTravail.created_at.desc())
        )
    ).scalars().all()
    dossier_bons = [
        LogementDossierBon(
            id=b.id,
            reference=b.reference,
            title=b.title,
            status=b.status,
            montant=float(b.amount) if b.amount is not None else None,
            created_at=b.created_at,
        )
        for b in bons
    ]

    # Fluctuation : loyers de bail en bail, en ordre chronologique.
    historique = [
        LoyerPoint(
            date_debut=b.date_debut,
            loyer_mensuel=float(b.loyer_mensuel or 0),
        )
        for b in sorted(baux, key=lambda x: x.date_debut)
    ]

    return LogementDossier(
        logement=LogementRead.model_validate(lg),
        immeuble=LogementDossierImmeuble(
            id=(imm.id if imm else lg.immeuble_id),
            name=(
                (imm.name or imm.address) if imm
                else f"Immeuble #{lg.immeuble_id}"
            ),
            address=(imm.address if imm else None),
        ),
        baux=dossier_baux,
        bons_travail=dossier_bons,
        historique_loyer=historique,
    )


# ── Locataires ─────────────────────────────────────────────────────────


@router.get("/locataires", response_model=List[LocataireRead])
async def list_locataires(
    db: DBSession, user: CurrentUser, search: Optional[str] = None
) -> List[LocataireRead]:
    _require_volet(user)
    q = select(Locataire).order_by(Locataire.full_name.asc())
    if search:
        q = q.where(Locataire.full_name.ilike(f"%{search}%"))
    rows = (await db.execute(q)).scalars().all()
    return [LocataireRead.model_validate(r) for r in rows]


@router.post(
    "/locataires",
    response_model=LocataireRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_locataire(
    payload: LocataireCreate, db: DBSession, user: CurrentUser
) -> LocataireRead:
    _require_volet(user)
    obj = Locataire(**payload.model_dump())
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return LocataireRead.model_validate(obj)


@router.get("/locataires/{locataire_id}", response_model=LocataireRead)
async def get_locataire(
    locataire_id: int, db: DBSession, user: CurrentUser
) -> LocataireRead:
    _require_volet(user)
    obj = await db.get(Locataire, locataire_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Locataire introuvable.")
    return LocataireRead.model_validate(obj)


@router.patch("/locataires/{locataire_id}", response_model=LocataireRead)
async def update_locataire(
    locataire_id: int,
    payload: LocataireUpdate,
    db: DBSession,
    user: CurrentUser,
) -> LocataireRead:
    _require_volet(user)
    obj = await db.get(Locataire, locataire_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Locataire introuvable.")
    data = payload.model_dump(exclude_unset=True)
    if "dpa_statut" in data and data["dpa_statut"] not in (
        "aucun", "envoye", "actif", "refuse"
    ):
        raise HTTPException(status_code=422, detail="Statut DPA invalide.")
    for k, v in data.items():
        setattr(obj, k, v)
    # Marquer l'accord signé/actif date automatiquement la signature.
    if data.get("dpa_statut") == "actif" and obj.dpa_signe_le is None:
        obj.dpa_signe_le = _now().date()
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return LocataireRead.model_validate(obj)


@router.delete(
    "/locataires/{locataire_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_locataire(
    locataire_id: int,
    db: DBSession,
    user: Annotated[User, Depends(require_capability("locataire.delete"))],
) -> None:
    _require_volet(user)
    obj = await db.get(Locataire, locataire_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Locataire introuvable.")
    await db.delete(obj)
    await db.commit()


@router.get(
    "/locataires/{locataire_id}/dossier", response_model=LocataireDossier
)
async def locataire_dossier(
    locataire_id: int, db: DBSession, user: CurrentUser
) -> LocataireDossier:
    """Fiche 360 d'un locataire : ses baux (avec immeuble/logement),
    l'historique complet de ses paiements de loyer et des agrégats."""
    _require_volet(user)
    loc = await db.get(Locataire, locataire_id)
    if loc is None:
        raise HTTPException(status_code=404, detail="Locataire introuvable.")

    baux = (
        await db.execute(
            select(Bail)
            .where(Bail.locataire_id == locataire_id)
            .order_by(Bail.date_debut.desc())
        )
    ).scalars().all()

    log_ids = {b.logement_id for b in baux if b.logement_id}
    log_by_id = {}
    if log_ids:
        for lg in (
            await db.execute(
                select(Logement).where(Logement.id.in_(list(log_ids)))
            )
        ).scalars().all():
            log_by_id[lg.id] = lg
    imm_ids = {lg.immeuble_id for lg in log_by_id.values()}
    imm_by_id = {}
    if imm_ids:
        for im in (
            await db.execute(
                select(Immeuble).where(Immeuble.id.in_(list(imm_ids)))
            )
        ).scalars().all():
            imm_by_id[im.id] = im

    dossier_baux = []
    for b in baux:
        lg = log_by_id.get(b.logement_id)
        im = imm_by_id.get(lg.immeuble_id) if lg else None
        dossier_baux.append(
            DossierBail(
                id=b.id,
                immeuble_id=(im.id if im else 0),
                immeuble_name=(im.name if im else "—"),
                logement_numero=(lg.numero if lg else None),
                date_debut=b.date_debut,
                date_fin=b.date_fin,
                loyer_mensuel=float(b.loyer_mensuel or 0),
                depot_garantie=(
                    float(b.depot_garantie)
                    if b.depot_garantie is not None
                    else None
                ),
                status=b.status,
            )
        )

    paiements = []
    bail_ids = [b.id for b in baux]
    if bail_ids:
        for pmt in (
            await db.execute(
                select(PaiementLoyer)
                .where(PaiementLoyer.bail_id.in_(bail_ids))
                .order_by(PaiementLoyer.mois_couvert.desc())
            )
        ).scalars().all():
            paiements.append(
                DossierPaiement(
                    id=pmt.id,
                    bail_id=pmt.bail_id,
                    mois_couvert=pmt.mois_couvert,
                    montant=float(pmt.montant or 0),
                    paye_le=pmt.paye_le,
                    methode=pmt.methode,
                    en_retard=bool(pmt.en_retard),
                )
            )

    # Avis d'augmentation / renouvellements de tous ses baux — le hub
    # locataire montre tout ce qui lui a été envoyé et où ça en est.
    renouvellements: list[DossierRenouvellement] = []
    if bail_ids:
        bail_by_id = {b.id: b for b in baux}
        for r in (
            await db.execute(
                select(BailRenouvellement)
                .where(BailRenouvellement.bail_id.in_(bail_ids))
                .order_by(BailRenouvellement.avis_envoye_le.desc())
            )
        ).scalars().all():
            rb = bail_by_id.get(r.bail_id)
            rlg = log_by_id.get(rb.logement_id) if rb else None
            rim = imm_by_id.get(rlg.immeuble_id) if rlg else None
            renouvellements.append(
                DossierRenouvellement(
                    id=r.id,
                    bail_id=r.bail_id,
                    immeuble_name=(rim.name if rim else "—"),
                    logement_numero=(rlg.numero if rlg else None),
                    avis_envoye_le=r.avis_envoye_le,
                    nouveau_loyer=(
                        float(r.nouveau_loyer)
                        if r.nouveau_loyer is not None
                        else None
                    ),
                    nouvelle_date_debut=r.nouvelle_date_debut,
                    nouvelle_date_fin=r.nouvelle_date_fin,
                    status=r.status,
                    locataire_repondu_le=r.locataire_repondu_le,
                    notes=r.notes,
                )
            )

    communications = [
        LocataireCommunicationRead.model_validate(c)
        for c in (
            await db.execute(
                select(LocataireCommunication)
                .where(LocataireCommunication.locataire_id == locataire_id)
                .order_by(LocataireCommunication.created_at.desc())
            )
        ).scalars().all()
    ]

    actifs = [b for b in baux if b.status == BailStatus.ACTIF.value]
    return LocataireDossier(
        locataire=LocataireRead.model_validate(loc),
        baux=dossier_baux,
        paiements=paiements,
        renouvellements=renouvellements,
        communications=communications,
        nb_baux_actifs=len(actifs),
        loyer_actuel=round(sum(float(b.loyer_mensuel or 0) for b in actifs), 2),
        depot_total=round(
            sum(float(b.depot_garantie or 0) for b in actifs), 2
        ),
        total_paye=round(
            sum(p.montant for p in paiements if p.paye_le is not None), 2
        ),
        nb_paiements=sum(1 for p in paiements if p.paye_le is not None),
        nb_retards=sum(1 for p in paiements if p.en_retard),
    )


# ─── Journal de communications du locataire (manuel) ────────────────────
# Pas de lien téléphonie (demande Phil 2026-07-10) : l'employé consigne
# lui-même appels/courriels/notes depuis la fiche du locataire.


@router.post(
    "/locataires/{locataire_id}/communications",
    response_model=LocataireCommunicationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_locataire_communication(
    locataire_id: int,
    payload: LocataireCommunicationCreate,
    db: DBSession,
    user: CurrentUser,
) -> LocataireCommunicationRead:
    _require_volet(user)
    loc = await db.get(Locataire, locataire_id)
    if loc is None:
        raise HTTPException(status_code=404, detail="Locataire introuvable.")
    contenu = (payload.contenu or "").strip()
    if not contenu:
        raise HTTPException(status_code=422, detail="Contenu requis.")
    kind = payload.kind if payload.kind in (
        "note", "appel", "courriel", "sms", "visite", "autre"
    ) else "note"
    obj = LocataireCommunication(
        locataire_id=locataire_id,
        kind=kind,
        contenu=contenu,
        auteur=getattr(user, "full_name", None) or user.email,
    )
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return LocataireCommunicationRead.model_validate(obj)


@router.delete(
    "/locataires/communications/{comm_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_locataire_communication(
    comm_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(LocataireCommunication, comm_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Entrée introuvable.")
    await db.delete(obj)
    await db.commit()


# ─── Dépôt préautorisé (DPA) — Règle H1, perception Desjardins ─────────


async def _dpa_contexte(db, locataire_id: int) -> dict:
    """Contexte du DPA depuis le bail ACTIF du locataire : loyer,
    adresse du logement, entreprise propriétaire (créancier)."""
    loc = await db.get(Locataire, locataire_id)
    if loc is None:
        raise HTTPException(status_code=404, detail="Locataire introuvable.")
    bail = (
        await db.execute(
            select(Bail)
            .where(
                Bail.locataire_id == locataire_id,
                Bail.status == BailStatus.ACTIF.value,
            )
            .order_by(Bail.date_debut.desc())
        )
    ).scalars().first()
    loyer = float(bail.loyer_mensuel) if bail and bail.loyer_mensuel else None
    adresse = ""
    creancier = "Le locateur"
    if bail is not None:
        lg = await db.get(Logement, bail.logement_id)
        im = await db.get(Immeuble, lg.immeuble_id) if lg else None
        if im is not None:
            adresse = f"{im.address}{', app. ' + lg.numero if lg else ''}"
            ownership = (
                await db.execute(
                    select(ImmeubleOwnership)
                    .where(ImmeubleOwnership.immeuble_id == im.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if ownership is not None:
                ent = await db.get(Entreprise, ownership.entreprise_id)
                if ent is not None:
                    creancier = ent.name
    return {
        "locataire": loc,
        "loyer": loyer,
        "adresse": adresse,
        "creancier": creancier,
    }


@router.get("/locataires/{locataire_id}/dpa/pdf")
async def dpa_pdf(
    locataire_id: int, db: DBSession, user: CurrentUser
) -> Response:
    """Formulaire d'accord DPA prérempli (PDF) — à faire remplir et
    signer par le locataire (renseignements bancaires + spécimen)."""
    _require_volet(user)
    from app.services.dpa_form import generate_dpa_pdf

    ctx = await _dpa_contexte(db, locataire_id)
    pdf = generate_dpa_pdf(
        locataire_nom=ctx["locataire"].full_name,
        logement_adresse=ctx["adresse"],
        creancier_nom=ctx["creancier"],
        loyer_mensuel=ctx["loyer"],
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="accord-dpa-{locataire_id}.pdf"'
            )
        },
    )


class DpaEnvoiResult(BaseModel):
    courriel_envoye: bool
    destinataire: Optional[str] = None


@router.post(
    "/locataires/{locataire_id}/dpa/envoyer",
    response_model=DpaEnvoiResult,
)
async def dpa_envoyer(
    locataire_id: int, db: DBSession, user: CurrentUser
) -> DpaEnvoiResult:
    """Envoi MANUEL de la documentation DPA au locataire (bouton —
    rien d'automatique) : courriel + formulaire d'accord PDF en pièce
    jointe. Le statut passe à « documentation envoyée »."""
    _require_volet(user)
    from app.integrations.email_graph import EmailAttachment, GraphMailer
    from app.services.dpa_form import generate_dpa_pdf

    ctx = await _dpa_contexte(db, locataire_id)
    loc = ctx["locataire"]
    if not (loc.email or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Le locataire n'a pas de courriel — ajoute-le d'abord.",
        )
    mailer = GraphMailer()
    if not mailer.ready:
        raise HTTPException(
            status_code=503,
            detail="Envoi courriel non configuré (Microsoft Graph).",
        )

    pdf = generate_dpa_pdf(
        locataire_nom=loc.full_name,
        logement_adresse=ctx["adresse"],
        creancier_nom=ctx["creancier"],
        loyer_mensuel=ctx["loyer"],
    )
    body_html = f"""
    <p>Bonjour {loc.full_name},</p>
    <p>Pour simplifier le paiement de votre loyer, nous vous proposons le
    <b>prélèvement bancaire préautorisé (DPA)</b> : le loyer est prélevé
    automatiquement de votre compte chaque mois — plus de chèque ni de
    virement à penser.</p>
    <p>Pour y adhérer :</p>
    <ol>
      <li>Remplissez et signez le formulaire ci-joint
      (« Accord de débit préautorisé ») ;</li>
      <li>Joignez un spécimen de chèque portant la mention « ANNULÉ » ;</li>
      <li>Retournez le tout en répondant à ce courriel.</li>
    </ol>
    <p>Vous pouvez annuler cette autorisation en tout temps avec un
    préavis écrit de 30 jours. Vos droits d'annulation et de
    remboursement sont détaillés dans le formulaire (www.paiements.ca).</p>
    <p>Cordialement,<br/>{ctx["creancier"]}</p>
    """.strip()
    try:
        await mailer.send(
            to=[loc.email],
            subject="Paiement du loyer par prélèvement préautorisé (DPA)",
            html_body=body_html,
            attachments=[
                EmailAttachment(
                    name="accord-dpa.pdf",
                    content_bytes=pdf,
                    content_type="application/pdf",
                )
            ],
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"Envoi du courriel échoué : {exc}"
        )

    loc.dpa_statut = "envoye"
    loc.dpa_envoye_le = _now().date()
    loc.updated_at = _now()
    await db.commit()
    return DpaEnvoiResult(courriel_envoye=True, destinataire=loc.email)


def _fmt_money_pdf(n) -> str:
    return f"{float(n or 0):,.0f} $".replace(",", "\u00a0")


def _render_etat_de_compte(
    loc, baux, log_by_id, imm_by_id, paiements,
    loyer_actuel, depot_total, total_paye,
):
    """Rend l'état de compte d'un locataire en PDF (reportlab)."""
    import io as _io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=2 * cm, bottomMargin=2 * cm,
        leftMargin=2 * cm, rightMargin=2 * cm,
        title="État de compte",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "h1", parent=styles["Heading1"], fontSize=18,
        textColor=colors.HexColor("#0f172a"),
    )
    h2 = ParagraphStyle(
        "h2", parent=styles["Heading2"], fontSize=12, spaceBefore=10,
        textColor=colors.HexColor("#0369a1"),
    )
    normal = styles["Normal"]
    small = ParagraphStyle(
        "small", parent=normal, fontSize=8,
        textColor=colors.HexColor("#64748b"),
    )
    today = datetime.now(timezone.utc).date()
    flow = [
        Paragraph("État de compte locataire", h1),
        Paragraph(
            f"Horizon Services Immobiliers — généré le {today.isoformat()}",
            small,
        ),
        Spacer(1, 0.4 * cm),
        Paragraph(loc.full_name or "—", h2),
    ]
    coords = [x for x in (loc.email, loc.phone) if x]
    if coords:
        flow.append(Paragraph(" · ".join(coords), normal))
    flow.append(Spacer(1, 0.3 * cm))

    grid = colors.HexColor("#cbd5e1")
    head_bg = colors.HexColor("#0369a1")

    summary = Table(
        [
            ["Loyer mensuel actuel", _fmt_money_pdf(loyer_actuel)],
            ["Dépôt de garantie détenu", _fmt_money_pdf(depot_total)],
            ["Total des loyers encaissés", _fmt_money_pdf(total_paye)],
        ],
        colWidths=[9 * cm, 4 * cm],
    )
    summary.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, grid),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    flow.append(summary)

    # Baux
    flow.append(Paragraph("Baux", h2))
    bail_rows = [["Immeuble / logement", "Période", "Loyer", "Dépôt", "Statut"]]
    for b in baux:
        lg = log_by_id.get(b.logement_id)
        im = imm_by_id.get(lg.immeuble_id) if lg else None
        name = (im.name if im else "—")
        if lg and lg.numero:
            name = f"{name} · {lg.numero}"
        bail_rows.append([
            name,
            f"{b.date_debut} → {b.date_fin}",
            _fmt_money_pdf(b.loyer_mensuel),
            _fmt_money_pdf(b.depot_garantie) if b.depot_garantie else "—",
            b.status,
        ])
    bt = Table(bail_rows, colWidths=[6 * cm, 4 * cm, 2.5 * cm, 2.2 * cm, 2.3 * cm])
    bt.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, grid),
        ("BACKGROUND", (0, 0), (-1, 0), head_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 1), (3, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(bt)

    # Paiements
    flow.append(Paragraph("Historique de paiements", h2))
    pay_rows = [["Mois couvert", "Montant", "Payé le", "Méthode", "État"]]
    for pm in paiements[:36]:
        if pm.paye_le is None:
            etat = "Impayé"
        elif pm.en_retard:
            etat = "Payé en retard"
        else:
            etat = "Payé"
        pay_rows.append([
            pm.mois_couvert.strftime("%Y-%m"),
            _fmt_money_pdf(pm.montant),
            pm.paye_le.isoformat() if pm.paye_le else "—",
            pm.methode or "—",
            etat,
        ])
    if len(pay_rows) == 1:
        pay_rows.append(["—", "—", "—", "—", "Aucun paiement"])
    pt = Table(pay_rows, colWidths=[3 * cm, 2.6 * cm, 3 * cm, 3 * cm, 3.4 * cm])
    pt.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, grid),
        ("BACKGROUND", (0, 0), (-1, 0), head_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(pt)

    flow.append(Spacer(1, 0.6 * cm))
    flow.append(Paragraph(
        "Document généré automatiquement par Kratos. Pour toute question, "
        "communiquez avec votre gestionnaire.",
        small,
    ))
    doc.build(flow)
    return buf.getvalue()


@router.get("/locataires/{locataire_id}/etat-de-compte.pdf")
async def locataire_etat_de_compte_pdf(
    locataire_id: int, db: DBSession, user: CurrentUser
) -> Response:
    """État de compte du locataire en PDF (baux, paiements, dépôt, solde)."""
    _require_volet(user)
    loc = await db.get(Locataire, locataire_id)
    if loc is None:
        raise HTTPException(status_code=404, detail="Locataire introuvable.")

    baux = (
        await db.execute(
            select(Bail)
            .where(Bail.locataire_id == locataire_id)
            .order_by(Bail.date_debut.desc())
        )
    ).scalars().all()
    log_ids = {b.logement_id for b in baux if b.logement_id}
    log_by_id = {}
    if log_ids:
        for lg in (
            await db.execute(
                select(Logement).where(Logement.id.in_(list(log_ids)))
            )
        ).scalars().all():
            log_by_id[lg.id] = lg
    imm_ids = {lg.immeuble_id for lg in log_by_id.values()}
    imm_by_id = {}
    if imm_ids:
        for im in (
            await db.execute(
                select(Immeuble).where(Immeuble.id.in_(list(imm_ids)))
            )
        ).scalars().all():
            imm_by_id[im.id] = im

    bail_ids = [b.id for b in baux]
    paiements = []
    if bail_ids:
        paiements = (
            await db.execute(
                select(PaiementLoyer)
                .where(PaiementLoyer.bail_id.in_(bail_ids))
                .order_by(PaiementLoyer.mois_couvert.desc())
            )
        ).scalars().all()

    actifs = [b for b in baux if b.status == BailStatus.ACTIF.value]
    # P-14 « PDF = reflet de la fiche » : on calcule les totaux EXACTEMENT
    # comme la fiche dossier locataire (même filtre baux actifs / paye_le +
    # round(2)), pour qu'aucun montant ne puisse diverger entre l'écran et
    # le PDF remis au locataire.
    loyer_actuel = round(sum(float(b.loyer_mensuel or 0) for b in actifs), 2)
    depot_total = round(sum(float(b.depot_garantie or 0) for b in actifs), 2)
    total_paye = round(
        sum(float(p.montant or 0) for p in paiements if p.paye_le is not None),
        2,
    )

    pdf = _render_etat_de_compte(
        loc, baux, log_by_id, imm_by_id, paiements,
        loyer_actuel, depot_total, total_paye,
    )
    safe = "".join(
        c if c.isalnum() else "-" for c in (loc.full_name or str(locataire_id))
    ).strip("-") or str(locataire_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="etat-de-compte-{safe}.pdf"'
        },
    )


# ── Dépôts de garantie ─────────────────────────────────────────────────


class DepotRow(BaseModel):
    bail_id: int
    immeuble_id: int
    immeuble_name: str
    logement_numero: Optional[str] = None
    locataire_id: Optional[int] = None
    locataire_name: Optional[str] = None
    montant: float
    # "detenu" | "a_rendre" | "rendu" | "aucun" (bail actif sans dépôt
    # saisi — permet de le saisir directement depuis la page Dépôts).
    statut: str
    depot_rendu_le: Optional[date] = None
    date_debut: date
    date_fin: date


class DepotOverview(BaseModel):
    rows: List[DepotRow] = []
    total_detenu: float = 0.0
    total_a_rendre: float = 0.0
    nb_a_rendre: int = 0
    total_rendu: float = 0.0
    nb_sans_depot: int = 0


@router.get("/depots/overview", response_model=DepotOverview)
async def depots_overview(
    db: DBSession, user: CurrentUser, entreprise_id: Optional[int] = None
) -> DepotOverview:
    """Suivi des dépôts de garantie : détenus (baux actifs) vs à rendre
    (baux terminés/résiliés). Sert à ne pas oublier de rembourser."""
    _require_volet(user)

    # Gestion externe : dépôts suivis par le gestionnaire tiers → exclu
    # (isnot(True) couvre les NULL legacy).
    imm_q = select(Immeuble).where(Immeuble.gestion_externe.isnot(True))
    if entreprise_id is not None:
        imm_q = imm_q.where(Immeuble.owner_entreprise_id == int(entreprise_id))
    immeubles = (await db.execute(imm_q)).scalars().all()
    visible = await visible_immeuble_ids(db, user)
    if visible is not None:
        immeubles = [i for i in immeubles if i.id in visible]
    imm_by_id = {i.id: i for i in immeubles}
    if not imm_by_id:
        return DepotOverview(rows=[])

    logements = (
        await db.execute(
            select(Logement).where(
                Logement.immeuble_id.in_(list(imm_by_id.keys()))
            )
        )
    ).scalars().all()
    log_by_id = {l.id: l for l in logements}
    if not log_by_id:
        return DepotOverview(rows=[])

    # TOUS les baux visibles — y compris les actifs SANS dépôt saisi
    # (statut « aucun ») pour permettre la saisie depuis la page Dépôts.
    baux = (
        await db.execute(
            select(Bail).where(
                Bail.logement_id.in_(list(log_by_id.keys())),
            )
        )
    ).scalars().all()

    loc_ids = {b.locataire_id for b in baux if b.locataire_id}
    loc_by_id = {}
    if loc_ids:
        for lo in (
            await db.execute(
                select(Locataire).where(Locataire.id.in_(list(loc_ids)))
            )
        ).scalars().all():
            loc_by_id[lo.id] = lo

    a_rendre_status = {
        BailStatus.TERMINE.value,
        BailStatus.RESILIE.value,
    }
    rows: List[DepotRow] = []
    total_detenu = 0.0
    total_a_rendre = 0.0
    total_rendu = 0.0
    for b in baux:
        lg = log_by_id.get(b.logement_id)
        im = imm_by_id.get(lg.immeuble_id) if lg else None
        if im is None:
            continue
        montant = float(b.depot_garantie or 0)
        if montant <= 0:
            # Bail sans dépôt : on n'affiche que les ACTIFS, comme ligne
            # « à saisir » — les baux passés sans dépôt n'apportent rien.
            if b.status != BailStatus.ACTIF.value:
                continue
            statut = "aucun"
        elif b.depot_rendu_le is not None:
            statut = "rendu"
            total_rendu += montant
        elif b.status in a_rendre_status:
            statut = "a_rendre"
            total_a_rendre += montant
        else:
            statut = "detenu"
            if b.status == BailStatus.ACTIF.value:
                total_detenu += montant
        loc = loc_by_id.get(b.locataire_id)
        rows.append(DepotRow(
            bail_id=b.id,
            immeuble_id=im.id,
            immeuble_name=im.name,
            logement_numero=(lg.numero if lg else None),
            locataire_id=loc.id if loc else None,
            locataire_name=loc.full_name if loc else None,
            montant=montant,
            statut=statut,
            depot_rendu_le=b.depot_rendu_le,
            date_debut=b.date_debut,
            date_fin=b.date_fin,
        ))

    rank = {"a_rendre": 0, "detenu": 1, "aucun": 2, "rendu": 3}
    rows.sort(key=lambda r: (rank.get(r.statut, 9), r.immeuble_name))
    return DepotOverview(
        rows=rows,
        total_detenu=round(total_detenu, 2),
        total_a_rendre=round(total_a_rendre, 2),
        nb_a_rendre=sum(1 for r in rows if r.statut == "a_rendre"),
        total_rendu=round(total_rendu, 2),
        nb_sans_depot=sum(1 for r in rows if r.statut == "aucun"),
    )


# ── Baux ───────────────────────────────────────────────────────────────


@router.get(
    "/immeubles/{immeuble_id}/baux", response_model=List[BailRead]
)
async def list_baux_for_immeuble(
    immeuble_id: int, db: DBSession, user: CurrentUser
) -> List[BailRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(Bail)
            .join(Logement, Logement.id == Bail.logement_id)
            .where(Logement.immeuble_id == immeuble_id)
            .order_by(Bail.date_debut.desc())
        )
    ).scalars().all()
    return [BailRead.model_validate(r) for r in rows]


@router.post(
    "/baux", response_model=BailRead, status_code=status.HTTP_201_CREATED
)
async def create_bail(
    payload: BailCreate, db: DBSession, user: CurrentUser
) -> BailRead:
    _require_volet(user)
    log_obj = await db.get(Logement, payload.logement_id)
    if log_obj is None:
        raise HTTPException(status_code=404, detail="Logement introuvable.")
    loc_obj = await db.get(Locataire, payload.locataire_id)
    if loc_obj is None:
        raise HTTPException(status_code=404, detail="Locataire introuvable.")

    obj = Bail(**payload.model_dump())
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)

    # Met à jour le statut du logement automatiquement
    if obj.status == BailStatus.ACTIF.value:
        log_obj.status = LogementStatus.OCCUPE.value
        log_obj.updated_at = _now()
    elif obj.status == BailStatus.PROPOSE.value:
        log_obj.status = LogementStatus.RESERVE.value
        log_obj.updated_at = _now()

    await db.commit()
    await db.refresh(obj)
    return BailRead.model_validate(obj)


@router.patch("/baux/{bail_id}", response_model=BailRead)
async def update_bail(
    bail_id: int,
    payload: BailUpdate,
    db: DBSession,
    user: CurrentUser,
) -> BailRead:
    _require_volet(user)
    obj = await db.get(Bail, bail_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Bail introuvable.")
    old_status = obj.status
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    obj.updated_at = _now()

    # Sync statut logement si bail terminé/résilié
    if (
        old_status == BailStatus.ACTIF.value
        and obj.status in (BailStatus.TERMINE.value, BailStatus.RESILIE.value)
    ):
        log_obj = await db.get(Logement, obj.logement_id)
        if log_obj is not None:
            log_obj.status = LogementStatus.VACANT.value
            log_obj.updated_at = _now()

    await db.commit()
    await db.refresh(obj)
    return BailRead.model_validate(obj)


@router.delete("/baux/{bail_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bail(
    bail_id: int,
    db: DBSession,
    user: Annotated[User, Depends(require_capability("bail.delete"))],
) -> None:
    _require_volet(user)
    obj = await db.get(Bail, bail_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Bail introuvable.")
    await db.delete(obj)
    await db.commit()


# ── Paiements de loyer ─────────────────────────────────────────────────


@router.get(
    "/baux/{bail_id}/paiements", response_model=List[PaiementLoyerRead]
)
async def list_paiements(
    bail_id: int, db: DBSession, user: CurrentUser
) -> List[PaiementLoyerRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(PaiementLoyer)
            .where(PaiementLoyer.bail_id == bail_id)
            .order_by(PaiementLoyer.mois_couvert.desc())
        )
    ).scalars().all()
    return [PaiementLoyerRead.model_validate(r) for r in rows]


@router.post(
    "/paiements",
    response_model=PaiementLoyerRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_paiement(
    payload: PaiementLoyerCreate, db: DBSession, user: CurrentUser
) -> PaiementLoyerRead:
    _require_volet(user)
    bail = await db.get(Bail, payload.bail_id)
    if bail is None:
        raise HTTPException(status_code=404, detail="Bail introuvable.")

    obj = PaiementLoyer(**payload.model_dump())
    obj.created_at = _now()
    # Marquer en retard si payé > 5 jours après le 1er du mois couvert
    if obj.paye_le and (obj.paye_le - obj.mois_couvert).days > 5:
        obj.en_retard = True
    db.add(obj)

    # Mettre à jour le score du locataire (basique : % paiements à temps)
    paiements = (
        await db.execute(
            select(PaiementLoyer).where(PaiementLoyer.bail_id == bail.id)
        )
    ).scalars().all()
    total = len(paiements) + 1
    en_retard = sum(1 for p in paiements if p.en_retard) + (
        1 if obj.en_retard else 0
    )
    score = max(0, min(100, round((1 - en_retard / total) * 100)))
    locataire = await db.get(Locataire, bail.locataire_id)
    if locataire is not None:
        locataire.paiement_score = score
        locataire.updated_at = _now()

    await db.commit()
    await db.refresh(obj)
    return PaiementLoyerRead.model_validate(obj)


@router.delete(
    "/paiements/{paiement_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_paiement(
    paiement_id: int,
    db: DBSession,
    user: Annotated[User, Depends(require_capability("paiement_loyer.delete"))],
) -> None:
    _require_volet(user)
    obj = await db.get(PaiementLoyer, paiement_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Paiement introuvable.")
    await db.delete(obj)
    await db.commit()


# ── Vue transversale « Loyers & retards » ─────────────────────────────
# Tous les baux actifs du portefeuille croisés avec les paiements d'un
# mois donné — LA vue quotidienne du gestionnaire (qui a payé, qui est
# en retard, marquer payé en 1 clic depuis la page Baux & paiements).


class LoyerOverviewRow(BaseModel):
    bail_id: int
    immeuble_id: int
    immeuble_name: str
    logement_numero: Optional[str] = None
    locataire_id: Optional[int] = None
    locataire_name: Optional[str] = None
    locataire_phone: Optional[str] = None
    loyer_mensuel: float
    paiement_id: Optional[int] = None
    montant_paye: Optional[float] = None
    paye_le: Optional[date] = None
    # "paye" | "retard" | "attente" (mois courant, pas encore au seuil)
    etat: str
    nb_relances: int = 0
    derniere_relance_le: Optional[date] = None


class LoyerOverview(BaseModel):
    mois: str
    rows: List[LoyerOverviewRow]
    total_attendu: float
    total_recu: float
    nb_payes: int
    nb_retards: int
    nb_attente: int


@router.get("/loyers/overview", response_model=LoyerOverview)
async def loyers_overview(
    db: DBSession,
    user: CurrentUser,
    mois: Optional[str] = None,
    entreprise_id: Optional[int] = None,
) -> LoyerOverview:
    """Croisement baux actifs × paiements pour un mois (def. courant).

    Un bail sans paiement pour le mois est « retard » passé le 5 du
    mois (même règle que le flag ``en_retard`` à la création d'un
    paiement), sinon « attente ».
    """
    _require_volet(user)

    today = datetime.now(timezone.utc).date()
    if mois:
        try:
            month_start = datetime.strptime(mois + "-01", "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Format mois attendu : YYYY-MM."
            )
    else:
        month_start = today.replace(day=1)
    month_label = month_start.strftime("%Y-%m")

    # Périmètre immeubles : filtre entreprise + visibilité employé.
    # Gestion externe : les loyers sont perçus par le gestionnaire tiers →
    # hors du suivi opérationnel. isnot(True) couvre aussi les NULL
    # (lignes créées avant le backfill du default).
    imm_q = select(Immeuble).where(
        Immeuble.is_active.is_(True),
        Immeuble.gestion_externe.isnot(True),
    )
    if entreprise_id is not None:
        imm_q = imm_q.where(
            Immeuble.owner_entreprise_id == int(entreprise_id)
        )
    immeubles = (await db.execute(imm_q)).scalars().all()
    visible = await visible_immeuble_ids(db, user)
    if visible is not None:
        immeubles = [i for i in immeubles if i.id in visible]
    imm_by_id = {i.id: i for i in immeubles}
    if not imm_by_id:
        return LoyerOverview(
            mois=month_label,
            rows=[],
            total_attendu=0.0,
            total_recu=0.0,
            nb_payes=0,
            nb_retards=0,
            nb_attente=0,
        )

    logements = (
        await db.execute(
            select(Logement).where(
                Logement.immeuble_id.in_(list(imm_by_id.keys()))
            )
        )
    ).scalars().all()
    log_by_id = {l.id: l for l in logements}

    baux = (
        await db.execute(
            select(Bail).where(
                Bail.logement_id.in_(list(log_by_id.keys())),
                Bail.status == BailStatus.ACTIF.value,
            )
        )
    ).scalars().all()

    locataires = {}
    loc_ids = {b.locataire_id for b in baux if b.locataire_id}
    if loc_ids:
        for loc in (
            await db.execute(
                select(Locataire).where(Locataire.id.in_(list(loc_ids)))
            )
        ).scalars().all():
            locataires[loc.id] = loc

    paiements_mois = {}
    bail_ids = [b.id for b in baux]
    if bail_ids:
        for p in (
            await db.execute(
                select(PaiementLoyer).where(
                    PaiementLoyer.bail_id.in_(bail_ids),
                    PaiementLoyer.mois_couvert == month_start,
                )
            )
        ).scalars().all():
            paiements_mois[p.bail_id] = p

    # Seuil de retard : après le 5 du mois couvert (ou mois passé).
    overdue_threshold = month_start.replace(day=5)
    rows: List[LoyerOverviewRow] = []
    total_attendu = 0.0
    total_recu = 0.0
    nb_payes = nb_retards = nb_attente = 0

    for b in baux:
        logement = log_by_id.get(b.logement_id)
        imm = imm_by_id.get(logement.immeuble_id) if logement else None
        if imm is None:
            continue
        loc = locataires.get(b.locataire_id)
        p = paiements_mois.get(b.id)
        loyer = float(b.loyer_mensuel or 0)
        total_attendu += loyer
        if p is not None:
            etat = "paye"
            nb_payes += 1
            total_recu += float(p.montant or 0)
        elif today > overdue_threshold:
            etat = "retard"
            nb_retards += 1
        else:
            etat = "attente"
            nb_attente += 1
        rows.append(
            LoyerOverviewRow(
                bail_id=b.id,
                immeuble_id=imm.id,
                immeuble_name=imm.name,
                logement_numero=(
                    logement.numero if logement is not None else None
                ),
                locataire_id=loc.id if loc else None,
                locataire_name=loc.full_name if loc else None,
                locataire_phone=loc.phone if loc else None,
                loyer_mensuel=loyer,
                paiement_id=p.id if p else None,
                montant_paye=float(p.montant) if p else None,
                paye_le=p.paye_le if p else None,
                etat=etat,
            )
        )

    # Relances de loyer envoyées ce mois (compteur + dernière) par bail.
    if rows:
        rel_rows = (
            await db.execute(
                select(RelanceLoyer).where(
                    RelanceLoyer.bail_id.in_([r.bail_id for r in rows]),
                    RelanceLoyer.mois_couvert == month_start,
                )
            )
        ).scalars().all()
        rel_by_bail: dict[int, list] = {}
        for rl in rel_rows:
            rel_by_bail.setdefault(rl.bail_id, []).append(rl)
        for r in rows:
            rls = rel_by_bail.get(r.bail_id) or []
            r.nb_relances = len(rls)
            if rls:
                r.derniere_relance_le = max(x.sent_at for x in rls).date()

    # Retards d'abord, puis attente, puis payés ; tri secondaire par
    # immeuble + logement pour une lecture stable.
    order = {"retard": 0, "attente": 1, "paye": 2}
    rows.sort(
        key=lambda r: (
            order.get(r.etat, 3),
            r.immeuble_name,
            r.logement_numero or "",
        )
    )

    return LoyerOverview(
        mois=month_label,
        rows=rows,
        total_attendu=round(total_attendu, 2),
        total_recu=round(total_recu, 2),
        nb_payes=nb_payes,
        nb_retards=nb_retards,
        nb_attente=nb_attente,
    )


class RelanceLoyerRequest(BaseModel):
    bail_id: int
    mois: Optional[str] = None  # YYYY-MM, défaut = mois courant


class RelanceLoyerResult(BaseModel):
    niveau: int
    destinataire: str
    mois: str


@router.post("/loyers/relance", response_model=RelanceLoyerResult)
async def relancer_loyer(
    payload: RelanceLoyerRequest, db: DBSession, user: CurrentUser
) -> RelanceLoyerResult:
    """Envoie une relance de loyer par courriel au locataire + la journalise.

    Le niveau s'incrémente par bail + mois (1er rappel, 2e rappel…). Sert de
    preuve avant un recours (mise en demeure TAL disponible à part).
    """
    _require_volet(user)
    bail = await db.get(Bail, payload.bail_id)
    if bail is None:
        raise HTTPException(status_code=404, detail="Bail introuvable.")
    loc = (
        await db.get(Locataire, bail.locataire_id)
        if bail.locataire_id
        else None
    )
    if loc is None or not (loc.email or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Ce locataire n'a pas de courriel — ajoute-le à sa fiche.",
        )

    today = datetime.now(timezone.utc).date()
    if payload.mois:
        try:
            month_start = datetime.strptime(
                payload.mois + "-01", "%Y-%m-%d"
            ).date()
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Format mois attendu : YYYY-MM."
            )
    else:
        month_start = today.replace(day=1)
    month_label = month_start.strftime("%Y-%m")
    mois_fr = month_start.strftime("%m/%Y")

    logement = (
        await db.get(Logement, bail.logement_id)
        if bail.logement_id
        else None
    )
    immeuble = (
        await db.get(Immeuble, logement.immeuble_id) if logement else None
    )

    existing = (
        await db.execute(
            select(RelanceLoyer).where(
                RelanceLoyer.bail_id == bail.id,
                RelanceLoyer.mois_couvert == month_start,
            )
        )
    ).scalars().all()
    niveau = len(existing) + 1

    # P-13 anti double-clic : si une relance a déjà été envoyée pour ce
    # bail + ce mois il y a moins de 5 min, on refuse (évite le double
    # courriel au locataire — preuve TAL — et l'escalade de niveau sur un
    # double-clic ou une relecture du bouton).
    now_dt = datetime.now(timezone.utc)
    for r in existing:
        last = r.sent_at
        if last is None:
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if now_dt - last < timedelta(minutes=5):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Une relance vient d'être envoyée pour ce loyer (il y a "
                    "moins de 5 minutes)."
                ),
            )

    loyer = float(bail.loyer_mensuel or 0)
    adresse = immeuble.name if immeuble else ""
    if logement and logement.numero:
        adresse = f"{adresse} — logement {logement.numero}"
    label = {1: "Premier rappel", 2: "Deuxième rappel"}.get(
        niveau, f"Rappel n°{niveau}"
    )
    dest = loc.email.strip()
    html = (
        f"<p>Bonjour {loc.full_name or ''},</p>"
        f"<p>{label} : nous n'avons pas encore reçu votre loyer de "
        f"<strong>{loyer:,.0f} $</strong> pour "
        f"<strong>{mois_fr}</strong>"
        + (f" ({adresse})" if adresse else "")
        + ".</p>"
        "<p>Si le paiement a déjà été effectué, "
        "merci d'ignorer ce message. Sinon, nous vous remercions de "
        "régulariser dans les meilleurs délais.</p>"
        "<p>Cordialement,<br/>Horizon Services Immobiliers</p>"
    )

    from app.integrations.email_graph import get_mailer

    # P-13 : on PERSISTE la relance (commit) AVANT d'envoyer le courriel —
    # la ligne sert de garde d'idempotence. L'index unique (bail, mois,
    # niveau) fait échouer un 2e insert simultané (double-clic concurrent)
    # → 409 au lieu d'un 2e courriel au locataire.
    rl = RelanceLoyer(
        bail_id=bail.id,
        mois_couvert=month_start,
        niveau=niveau,
        canal="courriel",
        destinataire=dest,
        sent_at=_now(),
        sent_by_email=getattr(user, "email", None),
    )
    db.add(rl)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Une relance pour ce loyer vient d'être enregistrée. "
                "Réessaie plus tard si nécessaire."
            ),
        )

    # Envoi best-effort APRÈS le commit. En cas d'échec, la ligne reste (le
    # gestionnaire voit l'erreur ; l'anti double-clic + l'index évitent tout
    # renvoi accidentel) — jamais de double courriel au locataire.
    try:
        await get_mailer().send(
            to=[dest],
            subject=f"Rappel de loyer — {mois_fr}",
            html_body=html,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=(
                "Relance enregistrée, mais l'envoi du courriel a échoué "
                f"({exc}). Vérifie la config courriel ou réessaie plus tard."
            ),
        )

    return RelanceLoyerResult(niveau=niveau, destinataire=dest, mois=month_label)


# ── Échéances de bail (avis de renouvellement) ─────────────────────────


class EcheanceRow(BaseModel):
    bail_id: int
    immeuble: str
    logement: str
    locataire: str
    date_fin: date
    fenetre_debut: date  # avis au plus tôt (≈ 6 mois avant la fin)
    fenetre_fin: date    # avis au plus tard (≈ 3 mois avant la fin)
    statut: str          # a_envoyer | en_retard | a_venir
    jours: int           # jours avant l'ouverture (a_venir) ou avant la fin
    loyer_mensuel: float


class EcheanceOverview(BaseModel):
    rows: List[EcheanceRow]
    nb_a_envoyer: int
    nb_en_retard: int
    nb_a_venir: int


@router.get("/baux/echeances", response_model=EcheanceOverview)
async def baux_echeances(
    db: DBSession,
    user: CurrentUser,
    entreprise_id: Optional[int] = None,
    horizon_jours: int = 45,
) -> EcheanceOverview:
    """Baux actifs dont la fenêtre d'avis de renouvellement approche.

    Au Québec, l'avis de modification d'un bail de 12 mois doit être
    transmis entre 6 et 3 mois avant la fin. On expose les baux dont la
    fenêtre s'ouvre bientôt (« à venir »), est ouverte (« à envoyer »),
    ou est dépassée mais le bail pas encore terminé (« en retard »). Les
    baux pour lesquels un avis a déjà été enregistré dans le cycle sont
    écartés.
    """
    _require_volet(user)
    today = datetime.now(timezone.utc).date()

    # Gestion externe : les avis de renouvellement relèvent du
    # gestionnaire tiers → exclu (isnot(True) couvre les NULL legacy).
    imm_q = select(Immeuble).where(
        Immeuble.is_active.is_(True),
        Immeuble.gestion_externe.isnot(True),
    )
    if entreprise_id is not None:
        imm_q = imm_q.where(
            Immeuble.owner_entreprise_id == int(entreprise_id)
        )
    immeubles = (await db.execute(imm_q)).scalars().all()
    visible = await visible_immeuble_ids(db, user)
    if visible is not None:
        immeubles = [i for i in immeubles if i.id in visible]
    imm_by_id = {i.id: i for i in immeubles}
    if not imm_by_id:
        return EcheanceOverview(
            rows=[], nb_a_envoyer=0, nb_en_retard=0, nb_a_venir=0
        )

    logements = (
        await db.execute(
            select(Logement).where(
                Logement.immeuble_id.in_(list(imm_by_id.keys()))
            )
        )
    ).scalars().all()
    log_by_id = {l.id: l for l in logements}

    baux = (
        await db.execute(
            select(Bail).where(
                Bail.logement_id.in_(list(log_by_id.keys())),
                Bail.status == BailStatus.ACTIF.value,
            )
        )
    ).scalars().all()

    loc_by_id: dict = {}
    loc_ids = {b.locataire_id for b in baux if b.locataire_id}
    if loc_ids:
        for loc in (
            await db.execute(
                select(Locataire).where(Locataire.id.in_(list(loc_ids)))
            )
        ).scalars().all():
            loc_by_id[loc.id] = loc

    # Avis déjà envoyés (par bail).
    renouv_by_bail: dict = {}
    bail_ids = [b.id for b in baux]
    if bail_ids:
        for r in (
            await db.execute(
                select(BailRenouvellement).where(
                    BailRenouvellement.bail_id.in_(bail_ids)
                )
            )
        ).scalars().all():
            renouv_by_bail.setdefault(r.bail_id, []).append(r.avis_envoye_le)

    rows: List[EcheanceRow] = []
    for b in baux:
        if not b.date_fin:
            continue
        window_start = b.date_fin - timedelta(days=183)
        window_end = b.date_fin - timedelta(days=91)
        # Avis déjà transmis dans ce cycle ?
        if any(
            d and d >= window_start for d in renouv_by_bail.get(b.id, [])
        ):
            continue
        if today >= b.date_fin:
            continue  # bail terminé (reconduit automatiquement)
        if today < window_start - timedelta(days=horizon_jours):
            continue  # trop loin pour alerter

        if today < window_start:
            statut, jours = "a_venir", (window_start - today).days
        elif today <= window_end:
            statut, jours = "a_envoyer", (window_end - today).days
        else:
            statut, jours = "en_retard", (b.date_fin - today).days

        logement = log_by_id.get(b.logement_id)
        immeuble = (
            imm_by_id.get(logement.immeuble_id) if logement else None
        )
        locataire = loc_by_id.get(b.locataire_id)
        rows.append(
            EcheanceRow(
                bail_id=b.id,
                immeuble=(immeuble.name if immeuble else "—"),
                logement=(logement.numero if logement else "—"),
                locataire=(
                    locataire.full_name if locataire else "—"
                ),
                date_fin=b.date_fin,
                fenetre_debut=window_start,
                fenetre_fin=window_end,
                statut=statut,
                jours=jours,
                loyer_mensuel=float(b.loyer_mensuel or 0),
            )
        )

    order = {"en_retard": 0, "a_envoyer": 1, "a_venir": 2}
    rows.sort(key=lambda r: (order.get(r.statut, 9), r.date_fin))
    return EcheanceOverview(
        rows=rows,
        nb_a_envoyer=sum(1 for r in rows if r.statut == "a_envoyer"),
        nb_en_retard=sum(1 for r in rows if r.statut == "en_retard"),
        nb_a_venir=sum(1 for r in rows if r.statut == "a_venir"),
    )


# ── Dépenses d'immeuble + P&L ──────────────────────────────────────────


class DepenseRead(BaseModel):
    id: int
    immeuble_id: int
    categorie: str
    libelle: str
    montant: float
    frequence: str
    # montant = % des loyers mensuels (ex. gestion à 5 %) au lieu d'un $.
    is_pourcentage: bool = False
    # taxable = appliquer TPS+TVQ Québec (×1.14975) dans les calculs.
    taxable: bool = False
    date_depense: Optional[date] = None
    notes: Optional[str] = None


class DepenseCreate(BaseModel):
    categorie: str = "autre"
    libelle: str
    montant: float = Field(..., ge=0)
    frequence: str = "ponctuel"
    is_pourcentage: bool = False
    taxable: bool = False
    date_depense: Optional[date] = None
    notes: Optional[str] = None


class DepenseUpdate(BaseModel):
    categorie: Optional[str] = None
    libelle: Optional[str] = None
    montant: Optional[float] = Field(default=None, ge=0)
    frequence: Optional[str] = None
    is_pourcentage: Optional[bool] = None
    taxable: Optional[bool] = None
    date_depense: Optional[date] = None
    notes: Optional[str] = None


def _depense_to_read(d: DepenseImmeuble) -> DepenseRead:
    return DepenseRead(
        id=d.id,
        immeuble_id=d.immeuble_id,
        categorie=d.categorie,
        libelle=d.libelle,
        montant=float(d.montant or 0),
        frequence=d.frequence,
        is_pourcentage=bool(d.is_pourcentage),
        taxable=bool(d.taxable),
        date_depense=d.date_depense,
        notes=d.notes,
    )


@router.get(
    "/immeubles/{immeuble_id}/depenses",
    response_model=List[DepenseRead],
)
async def list_depenses(
    immeuble_id: int, db: DBSession, user: CurrentUser
) -> List[DepenseRead]:
    _require_volet(user)
    await _require_immeuble_visible(db, user, immeuble_id)
    rows = (
        await db.execute(
            select(DepenseImmeuble)
            .where(DepenseImmeuble.immeuble_id == immeuble_id)
            .order_by(DepenseImmeuble.id.desc())
        )
    ).scalars().all()
    return [_depense_to_read(d) for d in rows]


@router.post(
    "/immeubles/{immeuble_id}/depenses",
    response_model=DepenseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_depense(
    immeuble_id: int,
    payload: DepenseCreate,
    db: DBSession,
    user: CurrentUser,
) -> DepenseRead:
    _require_volet(user)
    await _require_immeuble_visible(db, user, immeuble_id)
    await _get_immeuble_or_404(db, immeuble_id)
    obj = DepenseImmeuble(
        immeuble_id=immeuble_id,
        categorie=payload.categorie or "autre",
        libelle=payload.libelle.strip(),
        montant=payload.montant,
        frequence=(
            payload.frequence
            if payload.frequence in ("ponctuel", "mensuel", "annuel")
            else "ponctuel"
        ),
        is_pourcentage=payload.is_pourcentage,
        taxable=payload.taxable,
        date_depense=payload.date_depense,
        notes=payload.notes,
        created_by_email=user.email,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _depense_to_read(obj)


@router.put("/depenses/{depense_id}", response_model=DepenseRead)
async def update_depense(
    depense_id: int,
    payload: DepenseUpdate,
    db: DBSession,
    user: CurrentUser,
) -> DepenseRead:
    _require_volet(user)
    obj = await db.get(DepenseImmeuble, depense_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Dépense introuvable.")
    await _require_immeuble_visible(db, user, obj.immeuble_id)
    data = payload.model_dump(exclude_unset=True)
    if "frequence" in data and data["frequence"] not in (
        "ponctuel",
        "mensuel",
        "annuel",
    ):
        data.pop("frequence")
    for k, v in data.items():
        setattr(obj, k, v)
    await db.commit()
    await db.refresh(obj)
    return _depense_to_read(obj)


@router.delete(
    "/depenses/{depense_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_depense(
    depense_id: int,
    db: DBSession,
    user: Annotated[User, Depends(require_capability("depense.delete"))],
) -> None:
    _require_volet(user)
    obj = await db.get(DepenseImmeuble, depense_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Dépense introuvable.")
    await _require_immeuble_visible(db, user, obj.immeuble_id)
    await db.delete(obj)
    await db.commit()


class PnlRow(BaseModel):
    immeuble_id: int
    immeuble_name: str
    loyers_annualises: float
    revenus_recus: float
    depenses: float
    dette_annuelle: float
    cashflow_potentiel: float
    cashflow_reel: float
    nb_baux_actifs: int


class PnlOverview(BaseModel):
    annee: int
    rows: List[PnlRow]
    totaux: PnlRow


@router.get("/finances/pnl", response_model=PnlOverview)
async def finances_pnl(
    db: DBSession,
    user: CurrentUser,
    annee: Optional[int] = None,
    entreprise_id: Optional[int] = None,
) -> PnlOverview:
    """P&L annuel par immeuble.

    - revenus_recus : paiements de loyer enregistrés dans l'année ;
    - loyers_annualises : loyers des baux ACTIFS × 12 (potentiel) ;
    - depenses : ponctuelles datées dans l'année + récurrentes
      annualisées (mensuel × 12, annuel × 1) ;
    - dette_annuelle : paiements mensuels des hypothèques ACTIVES × 12 ;
    - cashflow_potentiel = loyers_annualises − depenses − dette ;
    - cashflow_reel = revenus_recus − depenses − dette.
    """
    _require_volet(user)
    year = annee or datetime.now(timezone.utc).year
    y_start = date(year, 1, 1)
    y_end = date(year, 12, 31)

    imm_q = select(Immeuble).where(Immeuble.is_active.is_(True))
    if entreprise_id is not None:
        imm_q = imm_q.where(
            Immeuble.owner_entreprise_id == int(entreprise_id)
        )
    immeubles = (await db.execute(imm_q)).scalars().all()
    visible = await visible_immeuble_ids(db, user)
    if visible is not None:
        immeubles = [i for i in immeubles if i.id in visible]
    imm_ids = [i.id for i in immeubles]

    rows: List[PnlRow] = []
    if imm_ids:
        logements = (
            await db.execute(
                select(Logement).where(Logement.immeuble_id.in_(imm_ids))
            )
        ).scalars().all()
        log_to_imm = {l.id: l.immeuble_id for l in logements}
        baux = []
        if log_to_imm:
            baux = (
                await db.execute(
                    select(Bail).where(
                        Bail.logement_id.in_(list(log_to_imm.keys())),
                        Bail.status == BailStatus.ACTIF.value,
                    )
                )
            ).scalars().all()
        bail_to_imm = {b.id: log_to_imm.get(b.logement_id) for b in baux}
        paiements = []
        if bail_to_imm:
            paiements = (
                await db.execute(
                    select(PaiementLoyer).where(
                        PaiementLoyer.bail_id.in_(list(bail_to_imm.keys())),
                        PaiementLoyer.mois_couvert >= y_start,
                        PaiementLoyer.mois_couvert <= y_end,
                    )
                )
            ).scalars().all()
        depenses = (
            await db.execute(
                select(DepenseImmeuble).where(
                    DepenseImmeuble.immeuble_id.in_(imm_ids)
                )
            )
        ).scalars().all()
        hypos = (
            await db.execute(
                select(Hypotheque).where(
                    Hypotheque.immeuble_id.in_(imm_ids),
                    Hypotheque.status == "ACTIVE",
                )
            )
        ).scalars().all()

        for imm in immeubles:
            loyers = sum(
                float(b.loyer_mensuel or 0) * 12
                for b in baux
                if bail_to_imm.get(b.id) == imm.id
            )
            recus = sum(
                float(p.montant or 0)
                for p in paiements
                if bail_to_imm.get(p.bail_id) == imm.id
            )
            dep = 0.0
            for d in depenses:
                if d.immeuble_id != imm.id:
                    continue
                if d.frequence == "mensuel":
                    dep += float(d.montant or 0) * 12
                elif d.frequence == "annuel":
                    dep += float(d.montant or 0)
                elif d.date_depense and y_start <= d.date_depense <= y_end:
                    dep += float(d.montant or 0)
            dette = sum(
                float(h.paiement_mensuel or 0) * 12
                for h in hypos
                if h.immeuble_id == imm.id
            )
            rows.append(
                PnlRow(
                    immeuble_id=imm.id,
                    immeuble_name=imm.name,
                    loyers_annualises=round(loyers, 2),
                    revenus_recus=round(recus, 2),
                    depenses=round(dep, 2),
                    dette_annuelle=round(dette, 2),
                    cashflow_potentiel=round(loyers - dep - dette, 2),
                    cashflow_reel=round(recus - dep - dette, 2),
                    nb_baux_actifs=sum(
                        1
                        for b in baux
                        if bail_to_imm.get(b.id) == imm.id
                    ),
                )
            )

    rows.sort(key=lambda r: r.cashflow_potentiel)
    tot = PnlRow(
        immeuble_id=0,
        immeuble_name="TOTAL",
        loyers_annualises=round(sum(r.loyers_annualises for r in rows), 2),
        revenus_recus=round(sum(r.revenus_recus for r in rows), 2),
        depenses=round(sum(r.depenses for r in rows), 2),
        dette_annuelle=round(sum(r.dette_annuelle for r in rows), 2),
        cashflow_potentiel=round(
            sum(r.cashflow_potentiel for r in rows), 2
        ),
        cashflow_reel=round(sum(r.cashflow_reel for r in rows), 2),
        nb_baux_actifs=sum(r.nb_baux_actifs for r in rows),
    )
    return PnlOverview(annee=year, rows=rows, totaux=tot)


# ── Prévisionnel (cashflow projeté) ────────────────────────────────────


class PrevisionnelMois(BaseModel):
    mois: str  # "YYYY-MM"
    revenus: float
    depenses_courantes: float
    hypotheque: float
    maintenance: float
    cashflow_net: float
    cashflow_cumule: float


class PrevisionnelOut(BaseModel):
    rows: List[PrevisionnelMois] = []
    revenus_mensuels: float = 0.0
    depenses_mensuelles: float = 0.0
    hypotheque_mensuelle: float = 0.0
    cashflow_mensuel_base: float = 0.0
    total_maintenance_planifiee: float = 0.0
    cashflow_horizon: float = 0.0


@router.get("/finances/previsionnel", response_model=PrevisionnelOut)
async def finances_previsionnel(
    db: DBSession,
    user: CurrentUser,
    mois: int = Query(default=12, ge=1, le=24),
    entreprise_id: Optional[int] = None,
    immeuble_id: Optional[int] = None,
) -> PrevisionnelOut:
    """Projection du cashflow sur N mois (déf. 12), à partir des données
    réelles : loyers des baux ACTIFS, dépenses récurrentes (mensuel ×1,
    annuel /12) + ponctuelles datées, paiements d'hypothèque, et maintenance
    PLANIFIÉE (cout_estime imputé au mois de sa date)."""
    _require_volet(user)

    imm_q = select(Immeuble).where(Immeuble.is_active.is_(True))
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
        return PrevisionnelOut()

    logements = (
        await db.execute(
            select(Logement).where(Logement.immeuble_id.in_(imm_ids))
        )
    ).scalars().all()
    log_ids = [lg.id for lg in logements]
    baux = []
    if log_ids:
        baux = (
            await db.execute(
                select(Bail).where(
                    Bail.logement_id.in_(log_ids),
                    Bail.status == BailStatus.ACTIF.value,
                )
            )
        ).scalars().all()
    revenus_mensuels = sum(float(b.loyer_mensuel or 0) for b in baux)

    depenses = (
        await db.execute(
            select(DepenseImmeuble).where(
                DepenseImmeuble.immeuble_id.in_(imm_ids)
            )
        )
    ).scalars().all()
    dep_mensuelles = 0.0
    pon_by_month: dict = {}
    for d in depenses:
        m = float(d.montant or 0)
        if d.frequence == "mensuel":
            dep_mensuelles += m
        elif d.frequence == "annuel":
            dep_mensuelles += m / 12.0
        elif d.date_depense:
            key = d.date_depense.strftime("%Y-%m")
            pon_by_month[key] = pon_by_month.get(key, 0.0) + m

    hypos = (
        await db.execute(
            select(Hypotheque).where(
                Hypotheque.immeuble_id.in_(imm_ids),
                Hypotheque.status.notin_(
                    ["remboursee", "refinancee", "REMBOURSEE", "REFINANCEE"]
                ),
            )
        )
    ).scalars().all()
    hyp_mensuelle = sum(float(h.paiement_mensuel or 0) for h in hypos)

    maints = (
        await db.execute(
            select(MaintenanceOrdre).where(
                MaintenanceOrdre.immeuble_id.in_(imm_ids),
                MaintenanceOrdre.plannifie_pour.is_not(None),
                MaintenanceOrdre.cout_estime.is_not(None),
            )
        )
    ).scalars().all()
    active_status = {"ouvert", "en_cours", "en_attente"}
    maint_by_month: dict = {}
    for mo in maints:
        if mo.status not in active_status:
            continue
        key = mo.plannifie_pour.strftime("%Y-%m")
        maint_by_month[key] = maint_by_month.get(key, 0.0) + float(
            mo.cout_estime or 0
        )

    today = datetime.now(timezone.utc).date()
    cur = today.replace(day=1)
    rows: List[PrevisionnelMois] = []
    cumule = 0.0
    total_maint = 0.0
    for _i in range(mois):
        key = cur.strftime("%Y-%m")
        maint = maint_by_month.get(key, 0.0)
        pon = pon_by_month.get(key, 0.0)
        dep_courantes = dep_mensuelles + pon
        cf = revenus_mensuels - dep_courantes - hyp_mensuelle - maint
        cumule += cf
        total_maint += maint
        rows.append(
            PrevisionnelMois(
                mois=key,
                revenus=round(revenus_mensuels, 2),
                depenses_courantes=round(dep_courantes, 2),
                hypotheque=round(hyp_mensuelle, 2),
                maintenance=round(maint, 2),
                cashflow_net=round(cf, 2),
                cashflow_cumule=round(cumule, 2),
            )
        )
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)

    return PrevisionnelOut(
        rows=rows,
        revenus_mensuels=round(revenus_mensuels, 2),
        depenses_mensuelles=round(dep_mensuelles, 2),
        hypotheque_mensuelle=round(hyp_mensuelle, 2),
        cashflow_mensuel_base=round(
            revenus_mensuels - dep_mensuelles - hyp_mensuelle, 2
        ),
        total_maintenance_planifiee=round(total_maint, 2),
        cashflow_horizon=round(cumule, 2),
    )


# ── Hypothèques ────────────────────────────────────────────────────────


def _hyp_read(obj: Hypotheque) -> HypothequeRead:
    """HypothequeRead + balance THÉORIQUE du jour (amortissement)."""
    from app.services.hypotheque_calc import balance_calculee_de

    r = HypothequeRead.model_validate(obj)
    r.balance_calculee = balance_calculee_de(obj)
    return r


@router.get(
    "/immeubles/{immeuble_id}/hypotheques",
    response_model=List[HypothequeRead],
)
async def list_hypotheques(
    immeuble_id: int, db: DBSession, user: CurrentUser
) -> List[HypothequeRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(Hypotheque)
            .where(Hypotheque.immeuble_id == immeuble_id)
            .order_by(Hypotheque.rang.asc())
        )
    ).scalars().all()
    return [_hyp_read(r) for r in rows]


def _pmt_hypotheque(obj: Hypotheque) -> float | None:
    """Paiement mensuel calculé depuis taux/amortissement/composition.

    Même math que le frontend (fiche immeuble) : composition
    semi-annuelle (standard résidentiel CA) ou mensuelle (commercial/
    variable), selon ``composition_interets``. Retourne None si les
    intrants manquent.
    """
    taux = float(obj.taux_pct) if obj.taux_pct is not None else None
    n = int(obj.amortissement_mois or 0)
    principal = float(
        obj.balance_actuelle
        if obj.balance_actuelle is not None
        else (obj.montant_initial or 0)
    )
    if taux is None or n <= 0 or principal <= 0:
        return None
    if (obj.composition_interets or "semi") == "mensuelle":
        i = taux / 100.0 / 12.0
    else:
        i = (1.0 + taux / 100.0 / 2.0) ** (2.0 / 12.0) - 1.0
    if i <= 0:
        return round(principal / n, 2)
    return round(principal * i / (1.0 - (1.0 + i) ** (-n)), 2)


def _maybe_recompute_pmt(obj: Hypotheque) -> None:
    """Si aucun paiement mensuel n'est fourni (créations API/MCP), le
    serveur le calcule — la fiche, le cashflow et les financials lisent
    tous la valeur persistée."""
    if obj.paiement_mensuel is None:
        pmt = _pmt_hypotheque(obj)
        if pmt is not None:
            obj.paiement_mensuel = pmt


@router.post(
    "/hypotheques",
    response_model=HypothequeRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_hypotheque(
    payload: HypothequeCreate, db: DBSession, user: CurrentUser
) -> HypothequeRead:
    _require_volet(user)
    await _get_immeuble_or_404(db, payload.immeuble_id)
    obj = Hypotheque(**payload.model_dump())
    _maybe_recompute_pmt(obj)
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _hyp_read(obj)


@router.patch("/hypotheques/{hyp_id}", response_model=HypothequeRead)
async def update_hypotheque(
    hyp_id: int,
    payload: HypothequeUpdate,
    db: DBSession,
    user: CurrentUser,
) -> HypothequeRead:
    _require_volet(user)
    obj = await db.get(Hypotheque, hyp_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Hypothèque introuvable.")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(obj, k, v)
    # Un intrant du calcul change sans paiement explicite → on recalcule
    # pour que la liste/cashflow/financials reflètent la modification.
    calc_keys = {
        "taux_pct", "amortissement_mois", "composition_interets",
        "balance_actuelle", "montant_initial",
    }
    if calc_keys & data.keys() and "paiement_mensuel" not in data:
        pmt = _pmt_hypotheque(obj)
        if pmt is not None:
            obj.paiement_mensuel = pmt
    else:
        _maybe_recompute_pmt(obj)
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return _hyp_read(obj)


@router.delete(
    "/hypotheques/{hyp_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_hypotheque(
    hyp_id: int,
    db: DBSession,
    user: Annotated[User, Depends(require_capability("hypotheque.delete"))],
) -> None:
    _require_volet(user)
    obj = await db.get(Hypotheque, hyp_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Hypothèque introuvable.")
    await db.delete(obj)
    await db.commit()


# ── Évaluations ────────────────────────────────────────────────────────


@router.get(
    "/immeubles/{immeuble_id}/evaluations",
    response_model=List[EvaluationRead],
)
async def list_evaluations(
    immeuble_id: int, db: DBSession, user: CurrentUser
) -> List[EvaluationRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(Evaluation)
            .where(Evaluation.immeuble_id == immeuble_id)
            .order_by(Evaluation.date_evaluation.desc())
        )
    ).scalars().all()
    return [EvaluationRead.model_validate(r) for r in rows]


@router.post(
    "/evaluations",
    response_model=EvaluationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_evaluation(
    payload: EvaluationCreate, db: DBSession, user: CurrentUser
) -> EvaluationRead:
    _require_volet(user)
    await _get_immeuble_or_404(db, payload.immeuble_id)
    if payload.is_reference:
        # Une seule évaluation de référence par immeuble.
        await db.execute(
            update(Evaluation)
            .where(Evaluation.immeuble_id == payload.immeuble_id)
            .values(is_reference=False)
        )
    obj = Evaluation(**payload.model_dump())
    obj.created_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return EvaluationRead.model_validate(obj)


@router.patch("/evaluations/{eval_id}", response_model=EvaluationRead)
async def update_evaluation(
    eval_id: int,
    payload: EvaluationUpdate,
    db: DBSession,
    user: CurrentUser,
) -> EvaluationRead:
    """Marque/démarque l'évaluation de référence pour le calcul d'équité.

    Passer ``is_reference=True`` remet automatiquement à False les
    autres évaluations du même immeuble (une seule référence)."""
    _require_volet(user)
    obj = await db.get(Evaluation, eval_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Évaluation introuvable.")
    data = payload.model_dump(exclude_unset=True)
    if data.get("is_reference") is True:
        await db.execute(
            update(Evaluation)
            .where(
                and_(
                    Evaluation.immeuble_id == obj.immeuble_id,
                    Evaluation.id != obj.id,
                )
            )
            .values(is_reference=False)
        )
    for k, v in data.items():
        setattr(obj, k, v)
    await db.commit()
    await db.refresh(obj)
    return EvaluationRead.model_validate(obj)


@router.delete(
    "/evaluations/{eval_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_evaluation(
    eval_id: int,
    db: DBSession,
    user: Annotated[User, Depends(require_capability("evaluation.delete"))],
) -> None:
    _require_volet(user)
    obj = await db.get(Evaluation, eval_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Évaluation introuvable.")
    await db.delete(obj)
    await db.commit()


# ── Maintenance ────────────────────────────────────────────────────────


@router.get(
    "/immeubles/{immeuble_id}/maintenance",
    response_model=List[MaintenanceOrdreRead],
)
async def list_maintenance(
    immeuble_id: int, db: DBSession, user: CurrentUser
) -> List[MaintenanceOrdreRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(MaintenanceOrdre)
            .where(MaintenanceOrdre.immeuble_id == immeuble_id)
            .order_by(MaintenanceOrdre.created_at.desc())
        )
    ).scalars().all()
    return [MaintenanceOrdreRead.model_validate(r) for r in rows]


@router.post(
    "/maintenance",
    response_model=MaintenanceOrdreRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_maintenance(
    payload: MaintenanceOrdreCreate, db: DBSession, user: CurrentUser
) -> MaintenanceOrdreRead:
    _require_volet(user)
    await _get_immeuble_or_404(db, payload.immeuble_id)
    obj = MaintenanceOrdre(**payload.model_dump())
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return MaintenanceOrdreRead.model_validate(obj)


@router.patch(
    "/maintenance/{ordre_id}", response_model=MaintenanceOrdreRead
)
async def update_maintenance(
    ordre_id: int,
    payload: MaintenanceOrdreUpdate,
    db: DBSession,
    user: CurrentUser,
) -> MaintenanceOrdreRead:
    _require_volet(user)
    obj = await db.get(MaintenanceOrdre, ordre_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Ordre introuvable.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return MaintenanceOrdreRead.model_validate(obj)


@router.delete(
    "/maintenance/{ordre_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_maintenance(
    ordre_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(MaintenanceOrdre, ordre_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Ordre introuvable.")
    await db.delete(obj)
    await db.commit()


_MAINT_ACTIVE = {"ouvert", "en_cours", "en_attente"}
_MAINT_STATUS_RANK = {
    "ouvert": 0, "en_cours": 1, "en_attente": 2, "termine": 3, "annule": 4,
}
_MAINT_PRIO_RANK = {"urgence": 0, "haute": 1, "normale": 2, "basse": 3}


@router.get("/maintenance/overview", response_model=MaintenanceOverview)
async def maintenance_overview(
    db: DBSession,
    user: CurrentUser,
    statut: Optional[str] = None,
    priorite: Optional[str] = None,
    immeuble_id: Optional[int] = None,
    inclure_termines: bool = False,
) -> MaintenanceOverview:
    """Vue transversale des ordres de maintenance sur tout le portefeuille.

    Les KPIs reflètent l'ensemble des ordres visibles ; les filtres
    (statut / priorité / immeuble) ne s'appliquent qu'aux lignes affichées.
    Tri : actifs d'abord, puis par priorité, puis du plus ancien (le plus
    en retard) au plus récent.
    """
    _require_volet(user)

    immeubles = (await db.execute(select(Immeuble))).scalars().all()
    visible = await visible_immeuble_ids(db, user)
    if visible is not None:
        immeubles = [i for i in immeubles if i.id in visible]
    if immeuble_id is not None:
        immeubles = [i for i in immeubles if i.id == int(immeuble_id)]
    imm_by_id = {i.id: i for i in immeubles}
    if not imm_by_id:
        return MaintenanceOverview(rows=[])

    ordres = (
        await db.execute(
            select(MaintenanceOrdre).where(
                MaintenanceOrdre.immeuble_id.in_(list(imm_by_id.keys()))
            )
        )
    ).scalars().all()

    log_ids = {o.logement_id for o in ordres if o.logement_id}
    log_by_id = {}
    if log_ids:
        for lg in (
            await db.execute(
                select(Logement).where(Logement.id.in_(list(log_ids)))
            )
        ).scalars().all():
            log_by_id[lg.id] = lg

    today = datetime.now(timezone.utc).date()
    kpi = {"ouvert": 0, "en_cours": 0, "en_attente": 0, "termine": 0, "annule": 0}
    nb_urg = 0
    tot_est = 0.0
    tot_reel = 0.0
    rows: List[MaintenanceOverviewRow] = []

    for o in ordres:
        if o.status in kpi:
            kpi[o.status] += 1
        active = o.status in _MAINT_ACTIVE
        if active and o.priorite == "urgence":
            nb_urg += 1
        if active and o.cout_estime is not None:
            tot_est += float(o.cout_estime)
        if o.cout_reel is not None:
            tot_reel += float(o.cout_reel)

        # Filtres d'affichage.
        if statut and o.status != statut:
            continue
        if priorite and o.priorite != priorite:
            continue
        if not inclure_termines and not statut and not active:
            continue

        jours = (
            (today - o.created_at.date()).days
            if (o.created_at and active)
            else None
        )
        lg = log_by_id.get(o.logement_id) if o.logement_id else None
        rows.append(
            MaintenanceOverviewRow(
                id=o.id,
                immeuble_id=o.immeuble_id,
                immeuble_name=imm_by_id[o.immeuble_id].name,
                logement_id=o.logement_id,
                logement_numero=(lg.numero if lg else None),
                titre=o.titre,
                description=o.description,
                priorite=o.priorite,
                status=o.status,
                fournisseur=o.fournisseur,
                cout_estime=(
                    float(o.cout_estime) if o.cout_estime is not None else None
                ),
                cout_reel=(
                    float(o.cout_reel) if o.cout_reel is not None else None
                ),
                plannifie_pour=o.plannifie_pour,
                complete_le=o.complete_le,
                created_at=o.created_at,
                jours_ouverts=jours,
            )
        )

    rows.sort(
        key=lambda r: (
            _MAINT_STATUS_RANK.get(r.status, 9),
            _MAINT_PRIO_RANK.get(r.priorite, 9),
            -(r.jours_ouverts or 0),
        )
    )
    return MaintenanceOverview(
        rows=rows,
        nb_total=len(rows),
        nb_ouvert=kpi["ouvert"],
        nb_en_cours=kpi["en_cours"],
        nb_en_attente=kpi["en_attente"],
        nb_termine=kpi["termine"],
        nb_annule=kpi["annule"],
        nb_urgences_actives=nb_urg,
        total_cout_estime_actif=round(tot_est, 2),
        total_cout_reel=round(tot_reel, 2),
    )


# ── Cockpit « À traiter » ──────────────────────────────────────────────


class ATraiterOut(BaseModel):
    loyers_retard_nb: int = 0
    loyers_retard_total: float = 0.0
    baux_a_renouveler_nb: int = 0
    maintenance_urgente_nb: int = 0
    depots_a_rendre_nb: int = 0
    depots_a_rendre_total: float = 0.0


@router.get("/a-traiter", response_model=ATraiterOut)
async def a_traiter(db: DBSession, user: CurrentUser) -> ATraiterOut:
    """Cockpit « À traiter » : agrège tout ce qui demande une action —
    loyers en retard, baux à renouveler, maintenance urgente, dépôts à
    rendre. Un coup d'œil pour ne rien échapper.

    Les immeubles en gestion externe sont exclus des compteurs loyers /
    renouvellements / dépôts via les overviews délégués ci-dessous."""
    _require_volet(user)
    # Appels internes : on passe TOUS les paramètres optionnels
    # explicitement (en appel direct, les défauts Query() ne valent pas None).
    lo = await loyers_overview(
        db=db, user=user, mois=None, entreprise_id=None
    )
    ech = await baux_echeances(
        db=db, user=user, entreprise_id=None, horizon_jours=45
    )
    maint = await maintenance_overview(
        db=db,
        user=user,
        statut=None,
        priorite=None,
        immeuble_id=None,
        inclure_termines=False,
    )
    dep = await depots_overview(db=db, user=user, entreprise_id=None)

    retard_total = sum(
        float(r.loyer_mensuel or 0) for r in lo.rows if r.etat == "retard"
    )
    return ATraiterOut(
        loyers_retard_nb=lo.nb_retards,
        loyers_retard_total=round(retard_total, 2),
        baux_a_renouveler_nb=ech.nb_a_envoyer + ech.nb_en_retard,
        maintenance_urgente_nb=maint.nb_urgences_actives,
        depots_a_rendre_nb=dep.nb_a_rendre,
        depots_a_rendre_total=dep.total_a_rendre,
    )


# ── KPIs financiers d'un immeuble ──────────────────────────────────────


@router.get(
    "/immeubles/{immeuble_id}/financials",
    response_model=ImmeubleFinancials,
)
async def get_financials(
    immeuble_id: int, db: DBSession, user: CurrentUser
) -> ImmeubleFinancials:
    _require_volet(user)
    imm = await _get_immeuble_or_404(db, immeuble_id)

    # Logements par statut
    log_rows = (
        await db.execute(
            select(Logement.status, func.count(Logement.id))
            .where(Logement.immeuble_id == immeuble_id)
            .group_by(Logement.status)
        )
    ).all()
    sts = {st: int(n) for st, n in log_rows}
    nb_actifs = sum(
        n for st, n in sts.items() if st != LogementStatus.HORS_LOC.value
    )
    nb_occ = sts.get(LogementStatus.OCCUPE.value, 0)
    taux = (nb_occ / nb_actifs) if nb_actifs > 0 else 0.0

    # Revenu brut mensuel PAR LOGEMENT : loyer du bail actif s'il existe,
    # SINON loyer demandé du logement (retour Phil 2026-07-10 : un
    # immeuble en gestion externe n'a pas de baux dans Kratos mais ses
    # loyers sont connus — le revenu ne doit pas afficher 0). Les
    # logements hors location sont exclus du fallback.
    logements_imm = (
        await db.execute(
            select(Logement).where(Logement.immeuble_id == immeuble_id)
        )
    ).scalars().all()
    baux_actifs_par_logement: dict[int, float] = {}
    for b in (
        await db.execute(
            select(Bail)
            .join(Logement, Logement.id == Bail.logement_id)
            .where(
                and_(
                    Logement.immeuble_id == immeuble_id,
                    Bail.status == BailStatus.ACTIF.value,
                )
            )
        )
    ).scalars().all():
        baux_actifs_par_logement[b.logement_id] = baux_actifs_par_logement.get(
            b.logement_id, 0.0
        ) + float(b.loyer_mensuel or 0)
    revenu = 0.0
    for lg in logements_imm:
        if lg.id in baux_actifs_par_logement:
            revenu += baux_actifs_par_logement[lg.id]
        elif (
            lg.status != LogementStatus.HORS_LOC.value
            and lg.loyer_demande is not None
        ):
            revenu += float(lg.loyer_demande)

    # Hypothèques actives. Balance EFFECTIVE par hypothèque : la balance
    # saisie prime, sinon la balance CALCULÉE au jour J (tableau
    # d'amortissement — « s'update toute seule », retour Phil 2026-07-10),
    # sinon le montant initial.
    from app.services.hypotheque_calc import balance_effective

    hyps_actives = (
        await db.execute(
            select(Hypotheque).where(
                and_(
                    Hypotheque.immeuble_id == immeuble_id,
                    Hypotheque.status == HypothequeStatus.ACTIVE.value,
                )
            )
        )
    ).scalars().all()
    paiement_hyp = sum(float(h.paiement_mensuel or 0) for h in hyps_actives)
    balance_hyp = round(sum(balance_effective(h) for h in hyps_actives), 2)

    # Valeur actuelle : l'évaluation marquée « référence » prime ;
    # sinon fallback sur la plus récente (toutes catégories).
    val_row = (
        await db.execute(
            select(Evaluation.valeur)
            .where(
                and_(
                    Evaluation.immeuble_id == immeuble_id,
                    Evaluation.is_reference.is_(True),
                )
            )
            .order_by(Evaluation.date_evaluation.desc())
            .limit(1)
        )
    ).scalar()
    if val_row is None:
        val_row = (
            await db.execute(
                select(Evaluation.valeur)
                .where(Evaluation.immeuble_id == immeuble_id)
                .order_by(Evaluation.date_evaluation.desc())
                .limit(1)
            )
        ).scalar()
    valeur_actuelle = float(val_row) if val_row is not None else None

    # Valeur municipale (la plus récente du kind=municipale)
    val_muni = (
        await db.execute(
            select(Evaluation.valeur)
            .where(
                and_(
                    Evaluation.immeuble_id == immeuble_id,
                    Evaluation.kind == EvaluationKind.MUNICIPALE.value,
                )
            )
            .order_by(Evaluation.date_evaluation.desc())
            .limit(1)
        )
    ).scalar()
    valeur_municipale = float(val_muni) if val_muni is not None else None

    # Si pas d'évaluation, fallback sur prix d'achat ou valeur municipale
    valeur_pour_ratios = (
        valeur_actuelle
        or valeur_municipale
        or (float(imm.purchase_price) if imm.purchase_price else None)
    )

    # Dépenses récurrentes mensualisées (même logique que l'onglet
    # Cashflow frontend) : mensuel → montant ; annuel → montant / 12 ;
    # ponctuel → exclu du flux récurrent. is_pourcentage → le montant
    # est un % des loyers mensuels. taxable → TPS+TVQ Québec ×1.14975.
    dep_rows = (
        await db.execute(
            select(
                DepenseImmeuble.montant,
                DepenseImmeuble.frequence,
                DepenseImmeuble.is_pourcentage,
                DepenseImmeuble.taxable,
            ).where(
                and_(
                    DepenseImmeuble.immeuble_id == immeuble_id,
                    DepenseImmeuble.frequence.in_(("mensuel", "annuel")),
                )
            )
        )
    ).all()
    depenses_mensuelles = 0.0
    for montant, frequence, is_pct, taxable in dep_rows:
        m = float(montant or 0)
        if is_pct:
            m = revenu * m / 100.0
        if frequence == "annuel":
            m = m / 12.0
        if taxable:
            m *= 1.14975
        depenses_mensuelles += m

    revenu_annuel = revenu * 12
    grm = (
        round(valeur_pour_ratios / revenu_annuel, 2)
        if valeur_pour_ratios and revenu_annuel > 0
        else None
    )
    # NOI : réel si ≥1 dépense récurrente saisie (revenus − dépenses
    # d'exploitation annualisées, SANS hypothèque), sinon fallback
    # heuristique NOI ≈ 50 % du revenu brut (règle du 50 %). Le flag
    # cap_rate_estime permet au front d'adapter le libellé.
    cap_rate_estime = len(dep_rows) == 0
    if cap_rate_estime:
        noi_annuel = revenu_annuel * 0.5
    else:
        noi_annuel = revenu_annuel - depenses_mensuelles * 12
    cap_rate = (
        round((noi_annuel / valeur_pour_ratios) * 100, 2)
        if valeur_pour_ratios and valeur_pour_ratios > 0
        else None
    )
    # Cash flow mensuel récurrent = loyers actifs − dépenses récurrentes
    # mensualisées − paiements hypothécaires actifs (aligné sur l'onglet
    # Cashflow frontend — le KPI du haut doit raconter la même histoire).
    cash_flow = round(revenu - depenses_mensuelles - paiement_hyp, 2)
    appreciation = None
    if imm.purchase_price and valeur_pour_ratios and float(imm.purchase_price) > 0:
        appreciation = round(
            ((valeur_pour_ratios - float(imm.purchase_price))
             / float(imm.purchase_price)) * 100,
            2,
        )

    return ImmeubleFinancials(
        immeuble_id=immeuble_id,
        nb_logements_actifs=nb_actifs,
        nb_logements_occupes=nb_occ,
        taux_occupation=round(taux, 4),
        revenu_brut_mensuel=round(revenu, 2),
        revenu_brut_annuel=round(revenu_annuel, 2),
        paiement_hypotheque_mensuel=round(paiement_hyp, 2),
        balance_hypothecaire=round(balance_hyp, 2),
        valeur_actuelle=valeur_actuelle,
        valeur_municipale=valeur_municipale,
        purchase_price=float(imm.purchase_price) if imm.purchase_price else None,
        grm=grm,
        cap_rate=cap_rate,
        cap_rate_estime=cap_rate_estime,
        cash_flow_mensuel=cash_flow,
        appreciation_pct=appreciation,
    )


# ── Import depuis le rôle d'évaluation MAMH ─────────────────────────────


@router.post(
    "/immeubles/import-matricule",
    response_model=ImmeubleImportResult,
    status_code=status.HTTP_201_CREATED,
)
async def import_immeuble_from_matricule(
    payload: ImmeubleImportFromMatriculeRequest,
    db: DBSession,
    user: CurrentUser,
) -> ImmeubleImportResult:
    """Crée un immeuble à partir d'un matricule MAMH déjà importé.

    Récupère depuis mtl_property_units :
    - adresse, code postal, municipalité
    - nb_logements
    - année de construction
    - superficies
    - valeur municipale (création d'une Evaluation kind=municipale)

    Si create_logements=True, crée des shells de logements (Apt 1..N)
    sans loyer ni statut — à compléter manuellement.
    """
    _require_volet(user)

    unit = (
        await db.execute(
            select(MontrealPropertyUnit).where(
                MontrealPropertyUnit.matricule == payload.matricule
            )
        )
    ).scalar_one_or_none()
    if unit is None:
        raise HTTPException(
            status_code=404,
            detail=f"Matricule {payload.matricule!r} introuvable dans le rôle d'évaluation.",
        )

    # Adresse complète depuis le rôle d'évaluation
    parts: List[str] = []
    civique = unit.civique_debut or ""
    if unit.civique_fin and unit.civique_fin != civique:
        civique = f"{civique}-{unit.civique_fin}" if civique else unit.civique_fin
    if civique:
        parts.append(str(civique))
    if unit.nom_rue:
        parts.append(str(unit.nom_rue))
    address = " ".join(parts) or "Adresse à compléter"

    name = payload.name or address
    nb_logements = unit.nombre_logement
    superficie_terrain = (
        float(unit.superficie_terrain) if unit.superficie_terrain else None
    )
    superficie_batiment = (
        float(unit.superficie_batiment) if unit.superficie_batiment else None
    )

    imm = Immeuble(
        name=name,
        address=address,
        city=unit.municipalite,
        type=ImmeubleType.RESIDENTIEL.value,
        annee_construction=unit.annee_construction,
        nb_logements=nb_logements,
        superficie_terrain=superficie_terrain,
        superficie_batiment=superficie_batiment,
        matricule=payload.matricule,
        is_active=True,
    )
    imm.created_at = _now()
    imm.updated_at = _now()
    db.add(imm)
    await db.flush()  # pour récupérer imm.id

    nb_crees = 0
    if payload.create_logements and nb_logements:
        for i in range(1, int(nb_logements) + 1):
            log_obj = Logement(
                immeuble_id=imm.id,
                numero=f"Apt {i}",
                type=ImmeubleType.RESIDENTIEL.value,
                status=LogementStatus.VACANT.value,
            )
            log_obj.created_at = _now()
            log_obj.updated_at = _now()
            db.add(log_obj)
            nb_crees += 1

    await db.commit()
    await db.refresh(imm)
    return ImmeubleImportResult(
        immeuble=_immeuble_to_read(imm),
        nb_logements_crees=nb_crees,
        matched_unit_id=getattr(unit, "id", None),
    )


# ── Import « rent roll » PlexFlow (copier-coller) ──────────────────────


def _norm_company(name: str) -> str:
    """Normalise un nom de compagnie pour le matching : minuscules, sans
    ponctuation, et sans les suffixes juridiques (« inc », « québec inc »,
    « ltée », etc.) que PlexFlow ajoute mais pas forcément Kratos.
    Ainsi « 9417-1287 Québec Inc. » et « 9417-1287 » correspondent."""
    s = (name or "").lower()
    s = re.sub(r"[.,]", " ", s)
    s = re.sub(
        r"\b(inc|québec|quebec|ltée|ltee|enr|senc|cie|co)\b", " ", s
    )
    return re.sub(r"\s+", " ", s).strip()


def _norm_address(addr: str) -> str:
    return re.sub(r"\s+", " ", (addr or "").strip().lower()).rstrip(",.")


@router.post("/import-plexflow", response_model=PlexImportResult)
async def import_plexflow(
    payload: PlexImportRequest, db: DBSession, user: CurrentUser
) -> PlexImportResult:
    """Parse un rent roll collé depuis PlexFlow et (si `dry_run=False`)
    crée immeubles + logements + locataires + baux, rattachés à la
    compagnie correspondante (match par nom). `dry_run=True` retourne
    seulement l'aperçu sans rien écrire."""
    _require_volet(user)
    companies, warnings = parse_plexflow(payload.raw_text)

    ent_rows = (await db.execute(select(Entreprise))).scalars().all()
    by_norm: dict[str, Entreprise] = {}
    for e in ent_rows:
        by_norm.setdefault(_norm_company(e.name), e)

    created = PlexImportCreated()
    out_companies: list[PlexImportCompany] = []

    # PlexFlow ne fournit pas les dates de bail : valeurs par défaut.
    today = _now().date()
    default_debut = today.replace(day=1)
    default_fin = default_debut + timedelta(days=365)
    import_note = (
        f"Importé de PlexFlow le {today.isoformat()} — dates à confirmer."
    )

    for comp in companies:
        # 1) override explicite fourni par l'utilisateur, sinon 2) match
        #    automatique par nom normalisé.
        ent = None
        override_id = payload.company_overrides.get(comp.name)
        if override_id:
            ent = await db.get(Entreprise, override_id)
        if ent is None:
            ent = by_norm.get(_norm_company(comp.name))
        oc = PlexImportCompany(
            name=comp.name,
            entreprise_id=ent.id if ent else None,
            matched=ent is not None,
        )

        existing_addr: set[str] = set()
        if ent is not None:
            rows = (
                await db.execute(
                    select(Immeuble.address)
                    .join(
                        ImmeubleOwnership,
                        ImmeubleOwnership.immeuble_id == Immeuble.id,
                    )
                    .where(ImmeubleOwnership.entreprise_id == ent.id)
                )
            ).scalars().all()
            existing_addr = {_norm_address(a) for a in rows if a}

        for b in comp.buildings:
            dup = _norm_address(b.address) in existing_addr
            units_out: list[PlexImportUnit] = []
            leases = 0
            for u in b.units:
                will_lease = bool(
                    u.tenant and u.rent and u.status in ("active", "scheduled")
                )
                if will_lease:
                    leases += 1
                units_out.append(
                    PlexImportUnit(
                        numero=u.numero,
                        tenant=u.tenant,
                        rent=u.rent,
                        status=u.status,
                        will_create_lease=will_lease,
                        warnings=list(u.warnings),
                    )
                )
            ob = PlexImportBuilding(
                address=b.address,
                city=b.city,
                postal_code=b.postal_code,
                nb_units=len(b.units),
                nb_leases=leases,
                already_exists=dup,
                units=units_out,
                warnings=list(b.warnings),
            )

            if not payload.dry_run and ent is not None and not dup:
                imm = Immeuble(
                    name=f"{b.address}, {b.city}" if b.city else b.address,
                    address=b.address,
                    city=b.city,
                    postal_code=b.postal_code,
                    type=ImmeubleType.RESIDENTIEL.value,
                    nb_logements=len(b.units),
                    is_active=True,
                )
                imm.created_at = _now()
                imm.updated_at = _now()
                db.add(imm)
                await db.flush()
                db.add(
                    ImmeubleOwnership(
                        immeuble_id=imm.id,
                        entreprise_id=ent.id,
                        ownership_pct=100.0,
                    )
                )
                created.immeubles += 1
                existing_addr.add(_norm_address(b.address))

                for u, pu in zip(b.units, units_out):
                    if pu.will_create_lease and u.status == "active":
                        lstatus = LogementStatus.OCCUPE.value
                    elif pu.will_create_lease and u.status == "scheduled":
                        lstatus = LogementStatus.RESERVE.value
                    else:
                        lstatus = LogementStatus.VACANT.value
                    log_obj = Logement(
                        immeuble_id=imm.id,
                        numero=(u.numero or "—")[:32],
                        type=ImmeubleType.RESIDENTIEL.value,
                        status=lstatus,
                        loyer_demande=u.rent,
                    )
                    log_obj.created_at = _now()
                    log_obj.updated_at = _now()
                    db.add(log_obj)
                    await db.flush()
                    created.logements += 1

                    if pu.will_create_lease:
                        loc = Locataire(full_name=(u.tenant or "")[:255])
                        loc.created_at = _now()
                        loc.updated_at = _now()
                        db.add(loc)
                        await db.flush()
                        created.locataires += 1
                        bail = Bail(
                            logement_id=log_obj.id,
                            locataire_id=loc.id,
                            date_debut=default_debut,
                            date_fin=default_fin,
                            loyer_mensuel=u.rent,
                            status=(
                                BailStatus.ACTIF.value
                                if u.status == "active"
                                else BailStatus.PROPOSE.value
                            ),
                            notes=import_note,
                        )
                        bail.created_at = _now()
                        bail.updated_at = _now()
                        db.add(bail)
                        created.baux += 1
            elif not payload.dry_run and dup:
                created.buildings_skipped += 1

            oc.buildings.append(ob)

        if not oc.matched:
            warnings.append(
                f"Compagnie « {comp.name} » introuvable dans Kratos — "
                "ses immeubles n'ont pas été importés."
            )
        out_companies.append(oc)

    if not payload.dry_run:
        await db.commit()

    totals = {
        "companies": len(out_companies),
        "companies_matched": sum(1 for c in out_companies if c.matched),
        "buildings": sum(len(c.buildings) for c in out_companies),
        "buildings_duplicate": sum(
            1 for c in out_companies for b in c.buildings if b.already_exists
        ),
        "units": sum(b.nb_units for c in out_companies for b in c.buildings),
        "leases": sum(b.nb_leases for c in out_companies for b in c.buildings),
    }

    return PlexImportResult(
        dry_run=payload.dry_run,
        companies=out_companies,
        totals=totals,
        created=None if payload.dry_run else created,
        warnings=warnings,
    )
