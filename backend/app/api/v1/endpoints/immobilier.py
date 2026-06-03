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
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select

from app.core.security import decode_token
from app.repositories.user import UserRepository

from app.api.deps import CurrentUser, DBSession
from app.models.entreprise import Entreprise
from app.models.bon_travail import BonTravail
from app.models.client import Client
from app.models.immobilier import (
    Bail,
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
    MaintenanceOrdre,
    PaiementLoyer,
)
from app.models.montreal_property_unit import MontrealPropertyUnit
from app.schemas.immobilier import (
    BailCreate,
    BailRead,
    BailUpdate,
    EvaluationCreate,
    EvaluationRead,
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
    LocataireCreate,
    LocataireRead,
    LocataireUpdate,
    LogementCreate,
    LogementRead,
    LogementUpdate,
    MaintenanceOrdreCreate,
    MaintenanceOrdreRead,
    MaintenanceOrdreUpdate,
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


# ── Helpers ─────────────────────────────────────────────────────────────


def _require_volet(user: CurrentUser) -> None:
    """Refuse l'accès si l'utilisateur n'a pas le volet immobilier."""
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion immobilière » non autorisé pour cet utilisateur.",
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


# ── Immeubles : liste + KPIs agrégés ────────────────────────────────────


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
    q = select(Immeuble).order_by(Immeuble.name.asc())
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


@router.get("/immeubles/{immeuble_id}/cover-photo")
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
    immeuble_id: int, db: DBSession, user: CurrentUser
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
    logement: Optional[str] = None  # n° de logement concerné (optionnel)


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

    loc = f" — logement {payload.logement}" if payload.logement else ""
    where = f"{imm.address}{(', ' + imm.city) if imm.city else ''}"
    scope = (
        f"Immeuble : {imm.name}{loc}\n"
        f"Adresse : {where}\n"
        "Source : Gestion immobilière (réparation)."
    )
    bon = BonTravail(
        reference=f"BON-{_now():%Y%m%d-%H%M%S}",
        title=payload.titre,
        description=payload.description,
        scope_md=scope,
        client_id=client.id if client else None,
        status="draft",
    )
    bon.created_at = _now()
    bon.updated_at = _now()
    db.add(bon)
    await db.commit()
    await db.refresh(bon)
    return {
        "bon_id": bon.id,
        "reference": bon.reference,
        "client_id": client.id if client else None,
        "client_name": ent.name if ent else None,
        "client_created": client_created,
    }


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
    logement_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(Logement, logement_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Logement introuvable.")
    await db.delete(obj)
    await db.commit()


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
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return LocataireRead.model_validate(obj)


@router.delete(
    "/locataires/{locataire_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_locataire(
    locataire_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(Locataire, locataire_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Locataire introuvable.")
    await db.delete(obj)
    await db.commit()


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
    bail_id: int, db: DBSession, user: CurrentUser
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
    paiement_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(PaiementLoyer, paiement_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Paiement introuvable.")
    await db.delete(obj)
    await db.commit()


# ── Hypothèques ────────────────────────────────────────────────────────


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
    return [HypothequeRead.model_validate(r) for r in rows]


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
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return HypothequeRead.model_validate(obj)


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
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return HypothequeRead.model_validate(obj)


@router.delete(
    "/hypotheques/{hyp_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_hypotheque(
    hyp_id: int, db: DBSession, user: CurrentUser
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
    obj = Evaluation(**payload.model_dump())
    obj.created_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return EvaluationRead.model_validate(obj)


@router.delete(
    "/evaluations/{eval_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_evaluation(
    eval_id: int, db: DBSession, user: CurrentUser
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

    # Revenu brut mensuel = Σ baux actifs
    revenu = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(Bail.loyer_mensuel), 0))
                .join(Logement, Logement.id == Bail.logement_id)
                .where(
                    and_(
                        Logement.immeuble_id == immeuble_id,
                        Bail.status == BailStatus.ACTIF.value,
                    )
                )
            )
        ).scalar()
        or 0
    )

    # Hypothèques actives
    hyp_rows = (
        await db.execute(
            select(
                func.coalesce(func.sum(Hypotheque.paiement_mensuel), 0),
                func.coalesce(func.sum(Hypotheque.balance_actuelle), 0),
            ).where(
                and_(
                    Hypotheque.immeuble_id == immeuble_id,
                    Hypotheque.status == HypothequeStatus.ACTIVE.value,
                )
            )
        )
    ).one()
    paiement_hyp = float(hyp_rows[0] or 0)
    balance_hyp = float(hyp_rows[1] or 0)

    # Valeur la plus récente (toutes catégories)
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

    revenu_annuel = revenu * 12
    grm = (
        round(valeur_pour_ratios / revenu_annuel, 2)
        if valeur_pour_ratios and revenu_annuel > 0
        else None
    )
    # NOI ≈ 50% du revenu brut (règle du 50% — placeholder en attendant
    # des charges réelles tracées dans le module Achats immobilier).
    noi_annuel = revenu_annuel * 0.5
    cap_rate = (
        round((noi_annuel / valeur_pour_ratios) * 100, 2)
        if valeur_pour_ratios and valeur_pour_ratios > 0
        else None
    )
    cash_flow = round(revenu - paiement_hyp, 2) if paiement_hyp >= 0 else None
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
