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
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
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
