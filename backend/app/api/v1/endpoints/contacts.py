"""Endpoints — Contacts (rolodex transverse + vue agrégée).

Deux familles d'endpoints :

1. **CRUD de la table `contacts` purs** :
   - GET/POST/PATCH/DELETE /api/v1/contacts

2. **Vue agrégée** (lecture seule, fédère plusieurs sources) :
   - GET /api/v1/contacts/all → liste unifiée incluant les contacts
     purs + sous-traitants Construction + fournisseurs + employés
     partenaires + sous-traitants Dev logiciel.

L'édition fine des entités fédérées reste sur leurs pages
spécialisées (/app/sous-traitants/{id}, /app/fournisseurs/{id}, …).
"""

from typing import List

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.contact import Contact
from app.models.devlog_sous_traitant import DevlogSousTraitant
from app.models.employe import Employe
from app.models.fournisseur import Fournisseur
from app.models.sous_traitant import SousTraitant
from app.repositories.generic import GenericCrud
from app.schemas.contact import (
    ContactCreate,
    ContactRead,
    ContactUpdate,
    UnifiedContact,
)


router = APIRouter(prefix="/contacts", tags=["contacts"])


# --------------------------------------------------------------------------
# Vue agrégée — DOIT être déclarée AVANT /{id} sinon "/all" matche
# /{id} avec id="all" et FastAPI renvoie 422.
# --------------------------------------------------------------------------


@router.get(
    "/all",
    response_model=List[UnifiedContact],
    summary="Liste unifiée de tous les contacts (toutes sources confondues)",
)
async def list_all_contacts(
    db: DBSession,
    _: CurrentUser,
    only_active: bool = Query(default=True),
):
    out: List[UnifiedContact] = []

    # 1) Contacts purs (table contacts)
    q = select(Contact)
    if only_active:
        q = q.where(Contact.active.is_(True))
    rows = (await db.execute(q)).scalars().all()
    for c in rows:
        out.append(
            UnifiedContact(
                id=f"contact:{c.id}",
                source="contact",
                source_id=c.id,
                full_name=c.full_name,
                company=c.company,
                email=c.email,
                phone=c.phone,
                address=c.address,
                kind=c.kind,
                specialty=c.specialty,
                active=c.active,
                detail_url=None,  # éditable inline
            )
        )

    # 2) Sous-traitants Construction
    q = select(SousTraitant)
    if only_active:
        q = q.where(SousTraitant.active.is_(True))
    rows = (await db.execute(q)).scalars().all()
    for s in rows:
        out.append(
            UnifiedContact(
                id=f"sous_traitant:{s.id}",
                source="sous_traitant",
                source_id=s.id,
                full_name=s.full_name,
                company=getattr(s, "contact_name", None),
                email=s.email,
                phone=s.phone,
                address=getattr(s, "address", None),
                kind="subcontractor",
                specialty=getattr(s, "trades", None),
                active=s.active,
                detail_url=f"/app/sous-traitants/{s.id}",
            )
        )

    # 3) Sous-traitants Dev logiciel
    q = select(DevlogSousTraitant)
    if only_active:
        q = q.where(DevlogSousTraitant.active.is_(True))
    rows = (await db.execute(q)).scalars().all()
    for s in rows:
        out.append(
            UnifiedContact(
                id=f"devlog_sous_traitant:{s.id}",
                source="devlog_sous_traitant",
                source_id=s.id,
                full_name=s.name,
                company=s.company,
                email=s.email,
                phone=s.phone,
                kind="devlog_subcontractor",
                specialty=s.specialty,
                active=s.active,
                detail_url=f"/dev-logiciel/sous-traitants/{s.id}",
            )
        )

    # 4) Fournisseurs
    q = select(Fournisseur)
    if only_active:
        q = q.where(Fournisseur.active.is_(True))
    rows = (await db.execute(q)).scalars().all()
    for f in rows:
        out.append(
            UnifiedContact(
                id=f"fournisseur:{f.id}",
                source="fournisseur",
                source_id=f.id,
                full_name=f.name,
                company=getattr(f, "contact_name", None),
                email=f.email,
                phone=f.phone,
                kind="supplier",
                specialty=getattr(f, "category", None),
                active=f.active,
                detail_url=f"/app/fournisseurs/{f.id}",
            )
        )

    # 5) Employés partenaires (is_partner=true) — pas les internes pour
    # ne pas polluer (les internes vivent dans la liste employés).
    q = select(Employe).where(Employe.is_partner.is_(True))
    if only_active:
        q = q.where(Employe.active.is_(True))
    rows = (await db.execute(q)).scalars().all()
    for e in rows:
        out.append(
            UnifiedContact(
                id=f"employe_partner:{e.id}",
                source="employe_partner",
                source_id=e.id,
                full_name=e.full_name,
                email=e.email,
                phone=e.phone,
                address=getattr(e, "address", None),
                kind="partner_employee",
                specialty=getattr(e, "role", None),
                active=e.active,
                detail_url=f"/app/employes/{e.id}",
            )
        )

    # Tri alphabétique par nom — l'UI peut re-trier en local.
    out.sort(key=lambda c: c.full_name.lower())
    return out


# --------------------------------------------------------------------------
# CRUD des contacts purs
# --------------------------------------------------------------------------


@router.get("", response_model=List[ContactRead])
async def list_contacts(
    db: DBSession,
    _: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
):
    return list(await GenericCrud(db, Contact).list(skip=skip, limit=limit))


@router.post(
    "", response_model=ContactRead, status_code=status.HTTP_201_CREATED
)
async def create_contact(
    data: ContactCreate, db: DBSession, _: CurrentUser
):
    obj = await GenericCrud(db, Contact).create(data)
    return ContactRead.model_validate(obj)


@router.get("/{contact_id}", response_model=ContactRead)
async def get_contact(contact_id: int, db: DBSession, _: CurrentUser):
    obj = await GenericCrud(db, Contact).get(contact_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    return ContactRead.model_validate(obj)


@router.patch("/{contact_id}", response_model=ContactRead)
async def update_contact(
    contact_id: int, data: ContactUpdate, db: DBSession, _: CurrentUser
):
    crud = GenericCrud(db, Contact)
    obj = await crud.get(contact_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    obj = await crud.update(obj, data)
    return ContactRead.model_validate(obj)


@router.delete(
    "/{contact_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_contact(contact_id: int, db: DBSession, _: CurrentUser):
    crud = GenericCrud(db, Contact)
    obj = await crud.get(contact_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    await crud.delete(obj)
