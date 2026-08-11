"""Endpoints CRUD partenaires + liens documentation pour le QG."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.entreprise import Entreprise, EntrepriseLink, EntreprisePartner
from app.models.user import User
from app.schemas.entreprise_partners_links import (
    LinkCreate,
    LinkRead,
    LinkUpdate,
    PartnerCreate,
    PartnerRead,
    PartnerUpdate,
)


log = logging.getLogger(__name__)
router = APIRouter(prefix="/entreprises", tags=["entreprises"])


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "entreprises" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion d'entreprises » non autorisé.",
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _hydrate_partner(db, p: EntreprisePartner) -> PartnerRead:
    out = PartnerRead.model_validate(p, from_attributes=True)
    if p.partner_name:
        out.display_name = p.partner_name
    elif p.user_id:
        u = await db.get(User, p.user_id)
        out.display_name = (
            getattr(u, "full_name", None) or u.email if u else f"Partenaire #{p.id}"
        )
    else:
        out.display_name = f"Partenaire #{p.id}"
    if p.partner_email:
        out.display_email = p.partner_email
    elif p.user_id:
        u = await db.get(User, p.user_id)
        out.display_email = u.email if u else None
    return out


# ─── Partners ──────────────────────────────────────────────────────────


@router.get("/partners-annuaire", response_model=List[PartnerRead])
async def partners_annuaire(
    db: DBSession, user: CurrentUser
) -> List[PartnerRead]:
    """Annuaire des partenaires déjà saisis (toutes entreprises
    confondues), dédupliqués — sert à préremplir le modal « Ajouter
    un partenaire » sans tout ressaisir (retour Phil 2026-08-10)."""
    _require_volet(user)
    rows = (
        await db.execute(
            select(EntreprisePartner).order_by(EntreprisePartner.id.desc())
        )
    ).scalars().all()
    seen: set = set()
    out: List[PartnerRead] = []
    for p in rows:
        key = (
            (p.partner_name or "").strip().lower(),
            (p.partner_email or "").strip().lower(),
            p.user_id,
        )
        if key == ("", "", None) or key in seen:
            continue
        seen.add(key)
        out.append(await _hydrate_partner(db, p))
    out.sort(key=lambda x: x.display_name.lower())
    return out


@router.get(
    "/{entreprise_id}/partners",
    response_model=List[PartnerRead],
)
async def list_partners(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> List[PartnerRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(EntreprisePartner)
            .where(EntreprisePartner.entreprise_id == entreprise_id)
            .order_by(EntreprisePartner.id.asc())
        )
    ).scalars().all()
    out: List[PartnerRead] = []
    for p in rows:
        out.append(await _hydrate_partner(db, p))
    return out


@router.post(
    "/partners",
    response_model=PartnerRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_partner(
    payload: PartnerCreate, db: DBSession, user: CurrentUser
) -> PartnerRead:
    _require_volet(user)
    ent = await db.get(Entreprise, payload.entreprise_id)
    if ent is None:
        raise HTTPException(404, "Entreprise introuvable.")
    if not payload.user_id and not payload.partner_name:
        raise HTTPException(
            400,
            "Fournis user_id ou partner_name pour identifier le partenaire.",
        )
    obj = EntreprisePartner(**payload.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return await _hydrate_partner(db, obj)


#: Champs d'IDENTITÉ d'un partenaire — modifiés sur une entreprise, ils
#: se propagent à TOUTES les entreprises où la même personne apparaît
#: (retour Phil 2026-08-10). Le rôle, le % de parts et les notes restent
#: propres à chaque entreprise.
_IDENTITY_FIELDS = (
    "partner_name",
    "partner_email",
    "partner_adresse",
    "partner_naissance",
    "partner_telephone",
    "is_personne_morale",
    "partner_neq",
)


async def _memes_personnes(
    db, obj: EntreprisePartner, old_name: str
) -> list[EntreprisePartner]:
    """Les AUTRES lignes partenaires qui représentent la même personne :
    même compte portail (user_id), sinon même nom (avant modification,
    insensible à la casse) parmi les partenaires sans compte."""
    if obj.user_id:
        return list(
            (
                await db.execute(
                    select(EntreprisePartner).where(
                        EntreprisePartner.user_id == obj.user_id,
                        EntreprisePartner.id != obj.id,
                    )
                )
            ).scalars().all()
        )
    if not old_name:
        return []
    rows = (
        await db.execute(
            select(EntreprisePartner).where(
                EntreprisePartner.user_id.is_(None),
                EntreprisePartner.id != obj.id,
            )
        )
    ).scalars().all()
    return [
        s
        for s in rows
        if (s.partner_name or "").strip().lower() == old_name
    ]


@router.patch("/partners/{partner_id}", response_model=PartnerRead)
async def update_partner(
    partner_id: int,
    payload: PartnerUpdate,
    db: DBSession,
    user: CurrentUser,
) -> PartnerRead:
    _require_volet(user)
    obj = await db.get(EntreprisePartner, partner_id)
    if obj is None:
        raise HTTPException(404, "Partenaire introuvable.")
    # Clé d'identité AVANT modification (le nom peut lui-même changer).
    old_name = (obj.partner_name or "").strip().lower()
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(obj, k, v)
    # Propagation des coordonnées à toutes les entreprises où la même
    # personne est partenaire.
    identity_changes = {
        k: v for k, v in data.items() if k in _IDENTITY_FIELDS
    }
    if identity_changes:
        for s in await _memes_personnes(db, obj, old_name):
            for k, v in identity_changes.items():
                setattr(s, k, v)
    await db.flush()
    await db.refresh(obj)
    return await _hydrate_partner(db, obj)


@router.delete(
    "/partners/{partner_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_partner(
    partner_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(EntreprisePartner, partner_id)
    if obj is None:
        raise HTTPException(404, "Partenaire introuvable.")
    await db.delete(obj)
    await db.flush()


# ─── Links externes (drive, sharepoint, dropbox…) ───────────────────────


@router.get(
    "/{entreprise_id}/links",
    response_model=List[LinkRead],
)
async def list_links(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> List[LinkRead]:
    _require_volet(user)
    rows = (
        await db.execute(
            select(EntrepriseLink)
            .where(EntrepriseLink.entreprise_id == entreprise_id)
            .order_by(EntrepriseLink.created_at.asc())
        )
    ).scalars().all()
    return [LinkRead.model_validate(r) for r in rows]


@router.post(
    "/links",
    response_model=LinkRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_link(
    payload: LinkCreate, db: DBSession, user: CurrentUser
) -> LinkRead:
    _require_volet(user)
    ent = await db.get(Entreprise, payload.entreprise_id)
    if ent is None:
        raise HTTPException(404, "Entreprise introuvable.")
    if not (payload.url.startswith("http://") or payload.url.startswith("https://")):
        raise HTTPException(
            400, "URL invalide — doit commencer par http(s)://"
        )
    obj = EntrepriseLink(**payload.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return LinkRead.model_validate(obj)


@router.patch("/links/{link_id}", response_model=LinkRead)
async def update_link(
    link_id: int,
    payload: LinkUpdate,
    db: DBSession,
    user: CurrentUser,
) -> LinkRead:
    _require_volet(user)
    obj = await db.get(EntrepriseLink, link_id)
    if obj is None:
        raise HTTPException(404, "Lien introuvable.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    return LinkRead.model_validate(obj)


@router.delete(
    "/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_link(
    link_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(EntrepriseLink, link_id)
    if obj is None:
        raise HTTPException(404, "Lien introuvable.")
    await db.delete(obj)
    await db.flush()
