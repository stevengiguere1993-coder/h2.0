"""Portail Investisseur v2 — console ADMIN (dans le pôle investisseur).

    GET    /invest/admin/projets                        tous les projets
    GET    /invest/admin/projets/{eid}                  détail complet
    PATCH  /invest/admin/projets/{eid}/profil           publication / description / phase
    POST   /invest/admin/participations                 lier (ou créer) un investisseur
    PATCH  /invest/admin/participations/{id}
    DELETE /invest/admin/participations/{id}
    POST   /invest/admin/participations/{id}/flux       apport / remboursement / dividende
    DELETE /invest/admin/flux/{id}
    POST   /invest/admin/projets/{eid}/jalons           jalon manuel de timeline
    DELETE /invest/admin/jalons/{id}
    POST   /invest/admin/projets/{eid}/documents        upload PDF partagé
    POST   /invest/admin/projets/{eid}/documents/from-drive   copie d'un fichier Drive coché
    GET    /invest/admin/documents/{id}/pdf
    DELETE /invest/admin/documents/{id}
    GET    /invest/admin/investisseurs                  comptes investisseurs
    POST   /invest/admin/investisseurs/{uid}/resend-invitation
    GET    /invest/admin/apercu/{uid}/portefeuille      « voir comme lui »
    GET    /invest/admin/apercu/{uid}/projets/{eid}

Registered dans router.py avec Depends(get_current_admin_or_owner) —
réservé à la direction, indépendamment du volet.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from app.api.deps import CurrentUser, DBSession
from app.core.security import get_password_hash
from app.models.entreprise import Entreprise
from app.models.invest_portal import (
    InvestDocument,
    InvestFlux,
    InvestFluxType,
    InvestJalon,
    InvestParticipation,
    InvestProjetProfil,
)
from app.models.user import User
from app.api.v1.endpoints.invest_portal import (
    build_portefeuille,
    build_projet,
)
from app.services.invest_invite import (
    InvestInviteError,
    generate_password,
    investor_volets_json,
    send_investor_invitation,
)
from app.services.invest_portfolio import (
    entreprise_snapshot,
    get_or_default_profil,
    kpis_participation,
    phase_projet,
    serie_mensuelle,
    timeline_projet,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/invest/admin", tags=["invest-admin"])

_FLUX_TYPES = {t.value for t in InvestFluxType}
_DOC_MAX_BYTES = 25 * 1024 * 1024


# ─────────────────────────── Schemas ───────────────────────────


class ProfilPatch(BaseModel):
    description: Optional[str] = Field(default=None, max_length=5000)
    phase_override: Optional[str] = Field(default=None, max_length=16)
    show_depenses: Optional[bool] = None
    show_hypotheque: Optional[bool] = None
    show_actionnaires: Optional[bool] = None
    show_cashflow: Optional[bool] = None


class NewInvestor(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=32)


class ParticipationCreate(BaseModel):
    entreprise_id: int
    user_id: Optional[int] = None
    new_investor: Optional[NewInvestor] = None
    parts_pct: float = Field(..., gt=0, le=100)
    is_visible: bool = True
    #: Apport initial optionnel créé en même temps.
    apport_initial: Optional[float] = Field(default=None, gt=0)
    apport_date: Optional[date] = None


class ParticipationPatch(BaseModel):
    parts_pct: Optional[float] = Field(default=None, gt=0, le=100)
    is_visible: Optional[bool] = None
    statut: Optional[str] = Field(default=None, max_length=16)
    notes: Optional[str] = Field(default=None, max_length=5000)


class FluxCreate(BaseModel):
    type: str
    montant: float = Field(..., gt=0)
    date_flux: date
    note: Optional[str] = Field(default=None, max_length=255)


class JalonCreate(BaseModel):
    date_jalon: date
    titre: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    kind: str = Field(default="autre", max_length=16)


class FromDriveRequest(BaseModel):
    file_id: str = Field(..., min_length=3, max_length=128)
    title: Optional[str] = Field(default=None, max_length=255)


# ─────────────────────────── Helpers ───────────────────────────


async def _load_entreprise(db, entreprise_id: int) -> Entreprise:
    ent = await db.get(Entreprise, entreprise_id)
    if ent is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Entreprise introuvable."
        )
    return ent


def _drive_folder_id(url: Optional[str]) -> Optional[str]:
    """Extrait l'ID de dossier d'une URL Google Drive."""
    if not url:
        return None
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", url)
    return m.group(1) if m else None


def _user_display(u: User) -> str:
    return (
        f"{u.first_name or ''} {u.last_name or ''}".strip() or u.email
    )


async def _participation_payload(db, part: InvestParticipation) -> dict:
    u = await db.get(User, part.user_id)
    flux = list(
        (
            await db.execute(
                select(InvestFlux)
                .where(InvestFlux.participation_id == part.id)
                .order_by(InvestFlux.date_flux, InvestFlux.id)
            )
        ).scalars()
    )
    snap_pct = float(part.parts_pct) / 100.0
    snap = await entreprise_snapshot(db, part.entreprise_id)
    valeur_parts = round(snap["equite"] * snap_pct, 2)
    k = kpis_participation(flux, valeur_parts)
    return {
        "id": part.id,
        "entreprise_id": part.entreprise_id,
        "user_id": part.user_id,
        "user_name": _user_display(u) if u else "—",
        "user_email": u.email if u else None,
        "parts_pct": float(part.parts_pct),
        "statut": part.statut,
        "is_visible": part.is_visible,
        "notes": part.notes,
        "valeur_parts": valeur_parts,
        **k,
        "flux": [
            {
                "id": f.id,
                "type": f.type,
                "montant": float(f.montant),
                "date_flux": f.date_flux.isoformat(),
                "note": f.note,
                "source": f.source,
            }
            for f in flux
        ],
    }


# ─────────────────────────── Projets ───────────────────────────


@router.get("/projets", summary="Tous les projets (vue admin)")
async def list_projets(db: DBSession, user: CurrentUser) -> List[dict]:
    ents = (
        await db.execute(
            select(Entreprise)
            .where(Entreprise.is_active.is_(True))
            .order_by(Entreprise.position, Entreprise.id)
        )
    ).scalars().all()
    parts_by_ent: dict[int, list[InvestParticipation]] = {}
    for p in (
        await db.execute(select(InvestParticipation))
    ).scalars().all():
        parts_by_ent.setdefault(p.entreprise_id, []).append(p)
    users_by_id: dict[int, User] = {}
    uids = {p.user_id for ps in parts_by_ent.values() for p in ps}
    if uids:
        for u in (
            await db.execute(select(User).where(User.id.in_(list(uids))))
        ).scalars().all():
            users_by_id[u.id] = u

    out: List[dict] = []
    for ent in ents:
        snap = await entreprise_snapshot(db, ent.id)
        parts = parts_by_ent.get(ent.id, [])
        if not snap["immeubles"] and not parts:
            continue  # entreprise sans immeuble ni investisseur — hors pôle
        capital_leve = 0.0
        investisseurs = []
        for p in parts:
            flux = list(
                (
                    await db.execute(
                        select(InvestFlux).where(
                            InvestFlux.participation_id == p.id
                        )
                    )
                ).scalars()
            )
            apports = sum(
                float(f.montant or 0)
                for f in flux
                if f.type == InvestFluxType.APPORT.value
            )
            capital_leve += apports
            u = users_by_id.get(p.user_id)
            investisseurs.append(
                {
                    "participation_id": p.id,
                    "user_id": p.user_id,
                    "name": _user_display(u) if u else "—",
                    "parts_pct": float(p.parts_pct),
                    "is_visible": p.is_visible,
                    "statut": p.statut,
                }
            )
        profil = await get_or_default_profil(db, ent.id)
        out.append(
            {
                "entreprise_id": ent.id,
                "name": ent.name,
                "color_accent": ent.color_accent,
                "phase": await phase_projet(db, ent.id, profil),
                "nb_immeubles": len(snap["immeubles"]),
                "nb_logements": snap["nb_logements"],
                "valeur_totale": snap["valeur_totale"],
                "equite": snap["equite"],
                "capital_leve": round(capital_leve, 2),
                "investisseurs": investisseurs,
            }
        )
    return out


@router.get("/projets/{entreprise_id}", summary="Détail admin d'un projet")
async def get_projet(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> dict:
    ent = await _load_entreprise(db, entreprise_id)
    snap = await entreprise_snapshot(db, entreprise_id)
    profil = await get_or_default_profil(db, entreprise_id)
    parts = (
        await db.execute(
            select(InvestParticipation)
            .where(InvestParticipation.entreprise_id == entreprise_id)
            .order_by(InvestParticipation.id)
        )
    ).scalars().all()
    participations = [
        await _participation_payload(db, p) for p in parts
    ]
    all_flux = list(
        (
            await db.execute(
                select(InvestFlux)
                .join(
                    InvestParticipation,
                    InvestParticipation.id == InvestFlux.participation_id,
                )
                .where(
                    InvestParticipation.entreprise_id == entreprise_id
                )
                .order_by(InvestFlux.date_flux)
            )
        ).scalars()
    )
    phase = await phase_projet(db, entreprise_id, profil)
    jalons = (
        await db.execute(
            select(InvestJalon)
            .where(InvestJalon.entreprise_id == entreprise_id)
            .order_by(InvestJalon.date_jalon)
        )
    ).scalars().all()
    docs = (
        await db.execute(
            select(InvestDocument)
            .where(InvestDocument.entreprise_id == entreprise_id)
            .order_by(InvestDocument.id.desc())
        )
    ).scalars().all()
    serie = await serie_mensuelle(db, entreprise_id)
    return {
        "entreprise_id": ent.id,
        "name": ent.name,
        "color_accent": ent.color_accent,
        "drive_folder_id": _drive_folder_id(ent.drive_folder_url),
        "phase": phase,
        "profil": {
            "description": profil.description if profil else None,
            "phase_override": profil.phase_override if profil else None,
            "show_depenses": profil.show_depenses if profil else True,
            "show_hypotheque": profil.show_hypotheque if profil else True,
            "show_actionnaires": (
                profil.show_actionnaires if profil else True
            ),
            "show_cashflow": profil.show_cashflow if profil else True,
        },
        **snap,
        "serie_mensuelle": serie["rows"],
        "hypotheque_mensuelle": serie["hypotheque_mensuelle"],
        "cashflow_moyen": serie["cashflow_moyen"],
        "participations": participations,
        "timeline": await timeline_projet(
            db, entreprise_id, all_flux, phase
        ),
        "jalons": [
            {
                "id": j.id,
                "date_jalon": j.date_jalon.isoformat(),
                "titre": j.titre,
                "description": j.description,
                "kind": j.kind,
            }
            for j in jalons
        ],
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "source": d.source,
                "size_bytes": d.size_bytes,
            }
            for d in docs
        ],
    }


@router.patch(
    "/projets/{entreprise_id}/profil",
    summary="Réglages de publication / description / phase",
)
async def patch_profil(
    entreprise_id: int, data: ProfilPatch, db: DBSession, user: CurrentUser
) -> dict:
    await _load_entreprise(db, entreprise_id)
    profil = await get_or_default_profil(db, entreprise_id)
    if profil is None:
        profil = InvestProjetProfil(entreprise_id=entreprise_id)
        db.add(profil)
        await db.flush()
    if "description" in data.model_fields_set:
        profil.description = (data.description or "").strip() or None
    if "phase_override" in data.model_fields_set:
        v = (data.phase_override or "").strip()
        if v and v not in ("optimisation", "long_terme"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Phase invalide (optimisation | long_terme).",
            )
        profil.phase_override = v or None
    for fld in (
        "show_depenses",
        "show_hypotheque",
        "show_actionnaires",
        "show_cashflow",
    ):
        val = getattr(data, fld)
        if val is not None:
            setattr(profil, fld, bool(val))
    await db.flush()
    await db.commit()
    return {"ok": True}


# ─────────────────────── Participations / flux ───────────────────────


@router.post(
    "/participations",
    status_code=status.HTTP_201_CREATED,
    summary="Lie un investisseur à une compagnie (compte créé au besoin)",
)
async def create_participation(
    data: ParticipationCreate, db: DBSession, user: CurrentUser
) -> dict:
    await _load_entreprise(db, data.entreprise_id)

    invitation_sent = False
    temp_password: Optional[str] = None
    target_user: Optional[User] = None

    if data.user_id:
        target_user = await db.get(User, data.user_id)
        if target_user is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Utilisateur introuvable."
            )
    elif data.new_investor:
        ni = data.new_investor
        email_norm = str(ni.email).strip().lower()
        target_user = (
            await db.execute(
                select(User).where(func.lower(User.email) == email_norm)
            )
        ).scalar_one_or_none()
        if target_user is None:
            pw = generate_password()
            target_user = User(
                email=email_norm,
                hashed_password=get_password_hash(pw),
                role="employee",
                is_active=True,
                must_change_password=True,
                volets_json=investor_volets_json(),
                first_name=ni.first_name.strip()[:100],
                last_name=ni.last_name.strip()[:100],
                phone_e164=(ni.phone or "").strip()[:32] or None,
            )
            db.add(target_user)
            await db.flush()
            try:
                await send_investor_invitation(
                    to_email=email_norm,
                    first_name=ni.first_name.strip(),
                    temporary_password=pw,
                    invited_by=user.email,
                )
                invitation_sent = True
            except InvestInviteError:
                # Compte créé quand même — l'admin transmet le mot de
                # passe lui-même (affiché UNE fois dans la réponse).
                temp_password = pw
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Fournissez user_id ou new_investor.",
        )

    existing = (
        await db.execute(
            select(InvestParticipation).where(
                InvestParticipation.user_id == target_user.id,
                InvestParticipation.entreprise_id == data.entreprise_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cet investisseur a déjà une participation dans cette "
            "compagnie.",
        )

    part = InvestParticipation(
        user_id=target_user.id,
        entreprise_id=data.entreprise_id,
        parts_pct=data.parts_pct,
        is_visible=data.is_visible,
    )
    db.add(part)
    await db.flush()
    if data.apport_initial:
        db.add(
            InvestFlux(
                participation_id=part.id,
                type=InvestFluxType.APPORT.value,
                montant=data.apport_initial,
                date_flux=data.apport_date or date.today(),
                note="Apport initial",
            )
        )
        await db.flush()
    await db.commit()
    payload = await _participation_payload(db, part)
    payload["invitation_sent"] = invitation_sent
    payload["temp_password"] = temp_password
    return payload


@router.patch("/participations/{part_id}", summary="Modifie une participation")
async def patch_participation(
    part_id: int, data: ParticipationPatch, db: DBSession, user: CurrentUser
) -> dict:
    part = await db.get(InvestParticipation, part_id)
    if part is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Participation introuvable."
        )
    if data.parts_pct is not None:
        part.parts_pct = data.parts_pct
    if data.is_visible is not None:
        part.is_visible = data.is_visible
    if data.statut is not None:
        if data.statut not in ("actif", "sorti"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Statut invalide (actif | sorti).",
            )
        part.statut = data.statut
    if "notes" in data.model_fields_set:
        part.notes = (data.notes or "").strip() or None
    await db.flush()
    await db.commit()
    return await _participation_payload(db, part)


@router.delete(
    "/participations/{part_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire une participation (et ses flux)",
)
async def delete_participation(
    part_id: int, db: DBSession, user: CurrentUser
) -> Response:
    part = await db.get(InvestParticipation, part_id)
    if part is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Participation introuvable."
        )
    await db.delete(part)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/participations/{part_id}/flux",
    status_code=status.HTTP_201_CREATED,
    summary="Ajoute un flux (apport, remboursement, distribution)",
)
async def create_flux(
    part_id: int, data: FluxCreate, db: DBSession, user: CurrentUser
) -> dict:
    part = await db.get(InvestParticipation, part_id)
    if part is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Participation introuvable."
        )
    if data.type not in _FLUX_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Type de flux invalide ({', '.join(sorted(_FLUX_TYPES))}).",
        )
    db.add(
        InvestFlux(
            participation_id=part.id,
            type=data.type,
            montant=data.montant,
            date_flux=data.date_flux,
            note=(data.note or "").strip()[:255] or None,
        )
    )
    await db.flush()
    await db.commit()
    return await _participation_payload(db, part)


@router.delete(
    "/flux/{flux_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprime un flux",
)
async def delete_flux(
    flux_id: int, db: DBSession, user: CurrentUser
) -> Response:
    f = await db.get(InvestFlux, flux_id)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Flux introuvable.")
    await db.delete(f)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─────────────────────────── Jalons ───────────────────────────


@router.post(
    "/projets/{entreprise_id}/jalons",
    status_code=status.HTTP_201_CREATED,
    summary="Ajoute un jalon manuel à la timeline",
)
async def create_jalon(
    entreprise_id: int, data: JalonCreate, db: DBSession, user: CurrentUser
) -> dict:
    await _load_entreprise(db, entreprise_id)
    if data.kind not in (
        "acquisition", "optimisation", "refinancement", "autre"
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Type de jalon invalide."
        )
    j = InvestJalon(
        entreprise_id=entreprise_id,
        date_jalon=data.date_jalon,
        titre=data.titre.strip()[:255],
        description=(data.description or "").strip() or None,
        kind=data.kind,
    )
    db.add(j)
    await db.flush()
    await db.commit()
    return {
        "id": j.id,
        "date_jalon": j.date_jalon.isoformat(),
        "titre": j.titre,
        "description": j.description,
        "kind": j.kind,
    }


@router.delete(
    "/jalons/{jalon_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprime un jalon",
)
async def delete_jalon(
    jalon_id: int, db: DBSession, user: CurrentUser
) -> Response:
    j = await db.get(InvestJalon, jalon_id)
    if j is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Jalon introuvable.")
    await db.delete(j)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─────────────────────────── Documents ───────────────────────────


@router.post(
    "/projets/{entreprise_id}/documents",
    status_code=status.HTTP_201_CREATED,
    summary="Téléverse un document partagé (PDF)",
)
async def upload_document(
    entreprise_id: int,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> dict:
    await _load_entreprise(db, entreprise_id)
    ct = (file.content_type or "").lower()
    if ct != "application/pdf":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Seuls les fichiers PDF sont acceptés.",
        )
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")
    if len(blob) > _DOC_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Document trop volumineux (max 25 Mo).",
        )
    doc = InvestDocument(
        entreprise_id=entreprise_id,
        uploaded_by_user_id=user.id,
        title=(file.filename or "document.pdf").rsplit(".", 1)[0][:255],
        source="upload",
        content_type="application/pdf",
        size_bytes=len(blob),
        blob=blob,
    )
    db.add(doc)
    await db.flush()
    await db.commit()
    return {
        "id": doc.id,
        "title": doc.title,
        "source": doc.source,
        "size_bytes": doc.size_bytes,
    }


@router.post(
    "/projets/{entreprise_id}/documents/from-drive",
    status_code=status.HTTP_201_CREATED,
    summary="Partage un fichier Drive coché (copie au moment du partage)",
)
async def document_from_drive(
    entreprise_id: int,
    data: FromDriveRequest,
    db: DBSession,
    user: CurrentUser,
) -> dict:
    await _load_entreprise(db, entreprise_id)
    try:
        from app.services import drive_api

        meta = await drive_api.get_file_metadata(
            user.id, db, data.file_id
        )
        blob = await drive_api.download_file(user.id, db, data.file_id)
    except Exception as exc:  # noqa: BLE001
        log.exception(
            "Copie Drive échouée (entreprise %s, fichier %s)",
            entreprise_id, data.file_id,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Copie depuis le Drive échouée : {exc}",
        ) from exc
    if not blob:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Fichier Drive vide."
        )
    if len(blob) > _DOC_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Document trop volumineux (max 25 Mo).",
        )
    name = (data.title or meta.get("name") or "document").rsplit(
        ".", 1
    )[0][:255]
    doc = InvestDocument(
        entreprise_id=entreprise_id,
        uploaded_by_user_id=user.id,
        title=name,
        source="drive",
        drive_file_id=data.file_id,
        content_type=meta.get("mimeType") or "application/pdf",
        size_bytes=len(blob),
        blob=blob,
    )
    db.add(doc)
    await db.flush()
    await db.commit()
    return {
        "id": doc.id,
        "title": doc.title,
        "source": doc.source,
        "size_bytes": doc.size_bytes,
    }


@router.get("/documents/{doc_id}/pdf", summary="Document partagé (admin)")
async def admin_document_pdf(
    doc_id: int, db: DBSession, user: CurrentUser
) -> Response:
    doc = (
        await db.execute(
            select(InvestDocument)
            .where(InvestDocument.id == doc_id)
            .options(undefer(InvestDocument.blob))
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Document introuvable."
        )
    return Response(
        content=bytes(doc.blob),
        media_type=doc.content_type or "application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{doc.title}.pdf"'
        },
    )


@router.delete(
    "/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire un document partagé",
)
async def delete_document(
    doc_id: int, db: DBSession, user: CurrentUser
) -> Response:
    doc = await db.get(InvestDocument, doc_id)
    if doc is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Document introuvable."
        )
    await db.delete(doc)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─────────────────────── Investisseurs (comptes) ───────────────────────


@router.get("/investisseurs", summary="Comptes investisseurs")
async def list_investisseurs(db: DBSession, user: CurrentUser) -> List[dict]:
    rows = (
        await db.execute(
            select(User, func.count(InvestParticipation.id))
            .join(
                InvestParticipation,
                InvestParticipation.user_id == User.id,
            )
            .group_by(User.id)
            .order_by(User.id)
        )
    ).all()
    return [
        {
            "user_id": u.id,
            "name": _user_display(u),
            "email": u.email,
            "phone": u.phone_e164,
            "is_active": u.is_active,
            "must_change_password": u.must_change_password,
            "nb_projets": int(n),
        }
        for u, n in rows
    ]


@router.post(
    "/investisseurs/{user_id}/resend-invitation",
    summary="Renvoie l'invitation (nouveau mot de passe temporaire)",
)
async def resend_invitation(
    user_id: int, db: DBSession, user: CurrentUser
) -> dict:
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Utilisateur introuvable."
        )
    nb = (
        await db.execute(
            select(func.count(InvestParticipation.id)).where(
                InvestParticipation.user_id == user_id
            )
        )
    ).scalar_one()
    if not nb:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Cet utilisateur n'a aucune participation.",
        )
    pw = generate_password()
    target.hashed_password = get_password_hash(pw)
    target.must_change_password = True
    await db.flush()
    await db.commit()
    try:
        await send_investor_invitation(
            to_email=target.email,
            first_name=target.first_name or "",
            temporary_password=pw,
            invited_by=user.email,
        )
        return {"sent": True, "temp_password": None}
    except InvestInviteError:
        return {"sent": False, "temp_password": pw}


# ─────────────────────── « Voir comme lui » ───────────────────────


@router.get(
    "/apercu/{user_id}/portefeuille",
    summary="Portefeuille tel que VU par cet investisseur",
)
async def apercu_portefeuille(
    user_id: int, db: DBSession, user: CurrentUser
) -> dict:
    return await build_portefeuille(db, user_id)


@router.get(
    "/apercu/{user_id}/projets/{entreprise_id}",
    summary="Fiche projet telle que VUE par cet investisseur",
)
async def apercu_projet(
    user_id: int, entreprise_id: int, db: DBSession, user: CurrentUser
) -> dict:
    return await build_projet(db, user_id, entreprise_id)
