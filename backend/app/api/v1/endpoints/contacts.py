"""Endpoints — Contacts (rolodex transverse + vue agrégée + import CSV).

Trois familles d'endpoints :

1. **CRUD de la table `contacts` purs** :
   - GET/POST/PATCH/DELETE /api/v1/contacts

2. **Vue agrégée** (lecture seule, fédère plusieurs sources) :
   - GET /api/v1/contacts/all

3. **Import CSV** depuis Gmail / Monday / autre :
   - POST /api/v1/contacts/import-csv (preview + commit)
"""

import csv
import io
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.contact import Contact
from app.models.contact_hide import ContactHide
from app.models.devlog_sous_traitant import DevlogSousTraitant
from app.models.employe import Employe
from app.models.fournisseur import Fournisseur
from app.models.sous_traitant import SousTraitant
from app.repositories.generic import GenericCrud
from app.schemas.contact import (
    ContactCreate,
    ContactHideRequest,
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
    include_hidden: bool = Query(default=False),
):
    # Précharge la set des (source, source_id) masqués pour filtrer
    # rapidement en mémoire. Petit volume attendu, OK de tout charger.
    hidden_rows = (await db.execute(select(ContactHide))).scalars().all()
    hidden_set = {(h.source, h.source_id) for h in hidden_rows}

    out: List[UnifiedContact] = []

    def _emit(uc: UnifiedContact) -> None:
        """Ajoute le contact à `out`, sauf s'il est masqué et qu'on
        n'a pas demandé `include_hidden=true`. Marque `hidden=true`
        sur les masqués gardés (pour affichage UI grisé)."""
        key = (uc.source, uc.source_id)
        if key in hidden_set:
            if not include_hidden:
                return
            uc.hidden = True
        out.append(uc)

    # 1) Contacts purs (table contacts)
    q = select(Contact)
    if only_active:
        q = q.where(Contact.active.is_(True))
    rows = (await db.execute(q)).scalars().all()
    for c in rows:
        _emit(
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
        _emit(
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
        _emit(
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
        _emit(
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
        _emit(
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


# --------------------------------------------------------------------------
# Import CSV (Gmail / Outlook / Monday / autre)
# --------------------------------------------------------------------------


# Mapping des en-têtes courants → champ Contact. La clé est en
# minuscules + accents stripés (cf. _norm_header). Les en-têtes Gmail
# (« E-mail 1 - Value ») et Monday (« Email ») sont tous couverts.
_HEADER_MAPPING: dict[str, str] = {
    # Nom
    "name": "full_name",
    "full name": "full_name",
    "given name": "full_name",  # Gmail
    "first name": "full_name",
    "nom complet": "full_name",
    "nom": "full_name",
    "person": "full_name",  # Monday person column
    # Entreprise / organisation
    "organization name": "company",
    "organization 1 - name": "company",  # Gmail
    "company": "company",
    "company name": "company",
    "entreprise": "company",
    "organisation": "company",
    # Email
    "email": "email",
    "e-mail": "email",
    "e-mail 1 - value": "email",  # Gmail
    "email 1 - value": "email",
    "email address": "email",
    "courriel": "email",
    # Téléphone
    "phone": "phone",
    "phone 1 - value": "phone",  # Gmail
    "phone number": "phone",
    "telephone": "phone",
    "tel": "phone",
    # Adresse
    "address": "address",
    "address 1 - formatted": "address",  # Gmail
    "address 1 - street": "address",
    "home address": "address",
    "adresse": "address",
    # Notes
    "notes": "notes",
    "note": "notes",
}


def _norm_header(h: str) -> str:
    """Normalise un en-tête : strip, lowercase, retire les accents."""
    import unicodedata

    s = (h or "").strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s


def _parse_csv(raw: bytes) -> tuple[list[str], list[dict]]:
    """Parse un CSV en (headers, rows). Détecte automatiquement le
    séparateur , vs ; et l'encodage (utf-8 / cp1252 fallback)."""
    text: Optional[str] = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(
            status_code=400,
            detail="Encodage du fichier non reconnu (utf-8, cp1252, latin-1).",
        )
    # Sniffer le séparateur sur les 4 KiB premiers.
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.get_dialect("excel")
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = list(reader.fieldnames or [])
    rows = [dict(r) for r in reader]
    return headers, rows


def _row_to_contact(row: dict) -> Optional[dict]:
    """Convertit une ligne CSV en payload Contact partiel. Retourne
    None si la ligne n'a ni nom ni email (ligne ignorable)."""
    out: dict = {}
    for h, raw_val in row.items():
        key = _HEADER_MAPPING.get(_norm_header(h))
        if not key:
            continue
        val = (raw_val or "").strip()
        if not val:
            continue
        if key in out and out[key]:
            # Gmail répète parfois plusieurs colonnes (email 1, 2…).
            # On garde la première non vide rencontrée.
            continue
        # Gmail concatène "given + family" via Name. Si Given Name +
        # Family Name dans des colonnes séparées, on les laisse aller
        # dans full_name dans l'ordre (first seen wins).
        out[key] = val[:500]
    name = out.get("full_name", "").strip()
    email = out.get("email", "").strip()
    if not name and not email:
        return None
    if not name:
        out["full_name"] = email.split("@", 1)[0]
    return out


class CsvImportResult(BaseModel):
    detected_rows: int
    inserted: int
    skipped_existing: int
    skipped_empty: int
    headers_matched: list[str]


@router.post(
    "/import-csv",
    response_model=CsvImportResult,
    summary="Import en masse de contacts depuis un CSV (Gmail / Monday / autre)",
)
async def import_contacts_csv(
    db: DBSession,
    _: CurrentUser,
    file: UploadFile,
    default_kind: str = Query(default="professional", max_length=32),
    dry_run: bool = Query(default=False),
    skip_duplicates_by_email: bool = Query(default=True),
):
    raw = await file.read()
    if not raw:
        raise HTTPException(
            status_code=400, detail="Fichier vide."
        )
    if len(raw) > 5_000_000:
        raise HTTPException(
            status_code=400,
            detail="Fichier trop volumineux (max 5 MB).",
        )
    headers, rows = _parse_csv(raw)

    # Liste des en-têtes effectivement mappés (pour feedback UI).
    matched: list[str] = []
    for h in headers:
        if _HEADER_MAPPING.get(_norm_header(h)):
            matched.append(h)

    # Précharge les emails existants pour la dédup.
    existing_emails: set[str] = set()
    if skip_duplicates_by_email:
        rs = (
            await db.execute(
                select(Contact.email).where(Contact.email.is_not(None))
            )
        ).all()
        existing_emails = {
            (e[0] or "").strip().lower() for e in rs if e[0]
        }

    inserted = 0
    skipped_existing = 0
    skipped_empty = 0
    for row in rows:
        payload = _row_to_contact(row)
        if payload is None:
            skipped_empty += 1
            continue
        email = (payload.get("email") or "").strip().lower()
        if (
            skip_duplicates_by_email
            and email
            and email in existing_emails
        ):
            skipped_existing += 1
            continue
        payload.setdefault("kind", default_kind)
        if not dry_run:
            db.add(Contact(**payload))
            if email:
                existing_emails.add(email)
        inserted += 1
    if not dry_run:
        await db.flush()
    return CsvImportResult(
        detected_rows=len(rows),
        inserted=inserted,
        skipped_existing=skipped_existing,
        skipped_empty=skipped_empty,
        headers_matched=matched,
    )


# --------------------------------------------------------------------------
# Masquage (hide) des contacts fédérés — purement cosmétique, l'entité
# d'origine (sous-traitant, fournisseur, employé) reste intacte.
# --------------------------------------------------------------------------


@router.post(
    "/hide",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Masquer un contact fédéré de la vue /entreprises/contacts",
)
async def hide_contact(
    data: ContactHideRequest, db: DBSession, user: CurrentUser
):
    # Idempotent : si déjà masqué, on no-op.
    existing = (
        await db.execute(
            select(ContactHide).where(
                ContactHide.source == data.source,
                ContactHide.source_id == data.source_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    db.add(
        ContactHide(
            source=data.source,
            source_id=data.source_id,
            hidden_by_user_id=getattr(user, "id", None),
        )
    )
    await db.flush()


@router.delete(
    "/hide/{source}/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Démasquer un contact fédéré",
)
async def unhide_contact(
    source: str, source_id: int, db: DBSession, _: CurrentUser
):
    existing = (
        await db.execute(
            select(ContactHide).where(
                ContactHide.source == source,
                ContactHide.source_id == source_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return
    await db.delete(existing)
    await db.flush()
