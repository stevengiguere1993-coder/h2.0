"""Endpoints CRUD partenaires + liens documentation pour le QG."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
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
    # Personne morale LIÉE à une de nos INCs : la fiche de la INC est la
    # source de vérité (nom, NEQ, siège social, contact) — pas de double
    # saisie.
    if p.partner_entreprise_id:
        ent_liee = await db.get(Entreprise, p.partner_entreprise_id)
        if ent_liee is not None:
            out.display_name = ent_liee.name
            out.partner_name = ent_liee.name
            out.partner_neq = ent_liee.neq or out.partner_neq
            out.partner_adresse = (
                getattr(ent_liee, "siege_social", None)
                or out.partner_adresse
            )
            out.partner_email = (
                getattr(ent_liee, "contact_email", None) or out.partner_email
            )
            out.partner_telephone = (
                getattr(ent_liee, "contact_telephone", None)
                or out.partner_telephone
            )
            out.display_email = out.partner_email
            out.is_personne_morale = True
    return out


async def _remonter_contact_vers_fiche(
    db, partner: EntreprisePartner
) -> None:
    """Sens INVERSE de l'interconnexion (retour Phil 2026-08-10) : les
    coordonnées saisies sur une ligne « INC actionnaire » remontent sur
    la FICHE de la INC quand celle-ci ne les a pas encore (fill-only —
    on n'écrase jamais une fiche déjà remplie)."""
    if not partner.partner_entreprise_id:
        return
    ent = await db.get(Entreprise, partner.partner_entreprise_id)
    if ent is None:
        return
    if partner.partner_email and not getattr(ent, "contact_email", None):
        ent.contact_email = partner.partner_email
    if partner.partner_telephone and not getattr(
        ent, "contact_telephone", None
    ):
        ent.contact_telephone = partner.partner_telephone
    if partner.partner_adresse and not getattr(ent, "siege_social", None):
        ent.siege_social = partner.partner_adresse
    if partner.partner_neq and not ent.neq:
        ent.neq = partner.partner_neq


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
        # Les lignes liées à une de nos INCs sont couvertes par les
        # entrées synthétiques ci-dessous (pas de doublon).
        if p.partner_entreprise_id:
            continue
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
    # NOS INCs — utilisables comme actionnaires d'une autre compagnie
    # (personne morale LIÉE à sa fiche : NEQ/adresse suivent la fiche).
    # id synthétique négatif : ces entrées ne sont pas des lignes BD.
    ents = (
        await db.execute(
            select(Entreprise)
            .where(Entreprise.is_active.is_(True))
            .order_by(Entreprise.name.asc())
        )
    ).scalars().all()
    # Filet : si la fiche n'a pas encore une coordonnée, on reprend
    # celle de la ligne partenaire LIÉE la plus récente de cette INC.
    liees: dict = {}
    for p in rows:
        if p.partner_entreprise_id and p.partner_entreprise_id not in liees:
            liees[p.partner_entreprise_id] = p
    for ent in ents:
        ligne = liees.get(ent.id)
        entry = PartnerRead(
            id=-ent.id,
            entreprise_id=ent.id,
            partner_name=ent.name,
            is_personne_morale=True,
            partner_neq=ent.neq or getattr(ligne, "partner_neq", None),
            partner_adresse=(
                getattr(ent, "siege_social", None)
                or getattr(ligne, "partner_adresse", None)
            ),
            partner_email=(
                getattr(ent, "contact_email", None)
                or getattr(ligne, "partner_email", None)
            ),
            partner_telephone=(
                getattr(ent, "contact_telephone", None)
                or getattr(ligne, "partner_telephone", None)
            ),
            partner_entreprise_id=ent.id,
        )
        entry.display_name = ent.name
        entry.display_email = entry.partner_email
        out.append(entry)
    return out


class ParticipationRead(BaseModel):
    """Une compagnie DONT cette INC est actionnaire (sens inverse de la
    liste des partenaires)."""

    entreprise_id: int
    entreprise_name: str
    ownership_pct: Optional[float] = None
    role: str = "associe"


@router.get(
    "/{entreprise_id}/participations",
    response_model=List[ParticipationRead],
)
async def list_participations(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> List[ParticipationRead]:
    """Les compagnies dont CETTE INC est actionnaire (lignes partenaires
    liées via partner_entreprise_id) — affichées sur sa fiche."""
    _require_volet(user)
    rows = (
        await db.execute(
            select(EntreprisePartner, Entreprise)
            .join(
                Entreprise,
                Entreprise.id == EntreprisePartner.entreprise_id,
            )
            .where(
                EntreprisePartner.partner_entreprise_id == entreprise_id
            )
            .order_by(Entreprise.name.asc())
        )
    ).all()
    return [
        ParticipationRead(
            entreprise_id=ent.id,
            entreprise_name=ent.name,
            ownership_pct=(
                float(p.ownership_pct)
                if p.ownership_pct is not None
                else None
            ),
            role=p.role or "associe",
        )
        for p, ent in rows
    ]


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
    if (
        not payload.user_id
        and not payload.partner_name
        and not payload.partner_entreprise_id
    ):
        raise HTTPException(
            400,
            "Fournis user_id ou partner_name pour identifier le partenaire.",
        )
    cible = None
    if payload.partner_entreprise_id:
        cible = await db.get(Entreprise, payload.partner_entreprise_id)
        if cible is None:
            raise HTTPException(404, "INC liée introuvable.")
        if cible.id == payload.entreprise_id:
            raise HTTPException(
                422,
                "Une compagnie ne peut pas être actionnaire d'elle-même.",
            )
    obj = EntreprisePartner(**payload.model_dump())
    if cible is not None:
        # Lien vers une de nos INCs : personne morale par définition, et
        # le nom vient de la fiche si non fourni.
        obj.is_personne_morale = True
        if not obj.partner_name:
            obj.partner_name = cible.name
    db.add(obj)
    await db.flush()
    # Coordonnées saisies ici → remontées sur la fiche de la INC liée
    # si elle ne les a pas (interconnexion dans les deux sens).
    await _remonter_contact_vers_fiche(db, obj)
    # L'organigramme (version Principal) reflète le nouvel actionnaire.
    from app.api.v1.endpoints.org_nodes import resync_detention_entreprise

    await resync_detention_entreprise(db, obj.entreprise_id)
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
    "partner_entreprise_id",
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
    if payload.partner_entreprise_id is not None:
        if payload.partner_entreprise_id == obj.entreprise_id:
            raise HTTPException(
                422,
                "Une compagnie ne peut pas être actionnaire d'elle-même.",
            )
        if await db.get(Entreprise, payload.partner_entreprise_id) is None:
            raise HTTPException(404, "INC liée introuvable.")
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
    # Coordonnées saisies ici → remontées sur la fiche de la INC liée
    # si elle ne les a pas (interconnexion dans les deux sens).
    await _remonter_contact_vers_fiche(db, obj)
    # L'organigramme (version Principal) reflète la modification.
    from app.api.v1.endpoints.org_nodes import resync_detention_entreprise

    await resync_detention_entreprise(db, obj.entreprise_id)
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
    ent_id = obj.entreprise_id
    await db.delete(obj)
    await db.flush()
    # L'organigramme (version Principal) reflète le retrait.
    from app.api.v1.endpoints.org_nodes import resync_detention_entreprise

    await resync_detention_entreprise(db, ent_id)


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
