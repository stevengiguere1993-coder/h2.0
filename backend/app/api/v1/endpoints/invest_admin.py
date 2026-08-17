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
from app.models.entreprise import Entreprise, EntreprisePartner
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
    effective_parts_pct,
    entreprise_snapshot,
    flux_signes,
    get_or_default_profil,
    kpis_participation,
    optimisation_projet_qbo,
    partner_directory,
    phase_projet,
    qbo_reels_data,
    serie_mensuelle,
    serie_valeur_totale,
    timeline_projet,
)
from app.services.invest_tri import xirr

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
    #: Avances aux actionnaires ($) — soustraites de l'équité.
    #: 0 ou null pour retirer.
    avances_actionnaires: Optional[float] = Field(default=None, ge=0)


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


def _partner_identity(
    pr: EntreprisePartner, pu: Optional[User]
) -> tuple[str, Optional[str]]:
    """(nom d'affichage, courriel) d'un partenaire.

    Le `partner_name` saisi dans la fiche entreprise PRIME sur le nom
    du User lié — c'est lui qui porte la réalité juridique (ex. un
    holding « Groupe X Investissement » dont le compte de connexion
    reste la personne physique)."""
    name = (
        (pr.partner_name or "").strip()
        or (_user_display(pu) if pu else "—")
    )
    email = ((pu.email if pu else pr.partner_email) or "").strip().lower()
    return name, (email or None)


def _ensure_volet_investisseur(u: User) -> None:
    """Cohabitation employé/gestionnaire ↔ investisseur : ajoute le
    volet `investisseur` au compte SANS toucher à ses autres accès.

    - owner/admin : déjà tous les volets, rien à faire ;
    - volets_json NULL = défauts implicites (construction, prospection,
      devlog) → on matérialise les défauts AVANT d'ajouter, sinon on
      les lui retirerait."""
    if u.role in ("owner", "admin"):
        return
    import json as _json

    from app.models.user import DEFAULT_VOLETS

    try:
        volets = (
            _json.loads(u.volets_json)
            if u.volets_json
            else list(DEFAULT_VOLETS)
        )
        if not isinstance(volets, list):
            volets = list(DEFAULT_VOLETS)
    except Exception:  # noqa: BLE001
        volets = list(DEFAULT_VOLETS)
    if "investisseur" not in volets:
        volets.append("investisseur")
        u.volets_json = _json.dumps(volets)


async def _resolve_partner_user(
    db, pr: EntreprisePartner
) -> Optional[User]:
    """User correspondant au partenaire : lien direct, sinon courriel."""
    if pr.user_id:
        u = await db.get(User, pr.user_id)
        if u is not None:
            return u
    email = (pr.partner_email or "").strip().lower()
    if email:
        return (
            await db.execute(
                select(User).where(func.lower(User.email) == email)
            )
        ).scalar_one_or_none()
    return None


async def _create_investor_account(
    db,
    *,
    first_name: str,
    last_name: str,
    email: str,
    phone: Optional[str],
    invited_by: str,
) -> tuple[User, bool, bool, Optional[str]]:
    """(user, créé?, invitation envoyée?, mot de passe si courriel KO).

    Réutilise un compte existant avec ce courriel (jamais de doublon)."""
    email_norm = email.strip().lower()
    existing = (
        await db.execute(
            select(User).where(func.lower(User.email) == email_norm)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False, False, None
    pw = generate_password()
    user = User(
        email=email_norm,
        hashed_password=get_password_hash(pw),
        role="employee",
        is_active=True,
        must_change_password=True,
        volets_json=investor_volets_json(),
        first_name=first_name.strip()[:100] or None,
        last_name=last_name.strip()[:100] or None,
        phone_e164=(phone or "").strip()[:32] or None,
    )
    db.add(user)
    await db.flush()
    try:
        await send_investor_invitation(
            to_email=email_norm,
            first_name=first_name.strip(),
            temporary_password=pw,
            invited_by=invited_by,
        )
        return user, True, True, None
    except InvestInviteError:
        return user, True, False, pw


async def _ensure_participation(
    db, user_id: int, entreprise_id: int, pct: Optional[float]
) -> tuple[InvestParticipation, bool]:
    """Participation (INVISIBLE par défaut) pour ce user/entreprise —
    créée au besoin, jamais dupliquée. Le % vient de la fiche
    entreprise (Parts & actionnaires), ajustable ensuite."""
    part = (
        await db.execute(
            select(InvestParticipation).where(
                InvestParticipation.user_id == user_id,
                InvestParticipation.entreprise_id == entreprise_id,
            )
        )
    ).scalar_one_or_none()
    if part is not None:
        return part, False
    part = InvestParticipation(
        user_id=user_id,
        entreprise_id=entreprise_id,
        parts_pct=pct if pct is not None else 0,
        is_visible=False,
    )
    db.add(part)
    await db.flush()
    return part, True


def _split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:]) or parts[0]


async def _participation_payload(
    db, part: InvestParticipation, directory: Optional[dict] = None
) -> dict:
    """Payload d'une participation. Les PARTS et le NOM viennent de la
    fiche entreprise (Parts & actionnaires) quand l'actionnaire y est
    apparié — la console ne les édite plus."""
    u = await db.get(User, part.user_id)
    if directory is None:
        directory = await partner_directory(db, part.entreprise_id)
    flux = list(
        (
            await db.execute(
                select(InvestFlux)
                .where(InvestFlux.participation_id == part.id)
                .order_by(InvestFlux.date_flux, InvestFlux.id)
            )
        ).scalars()
    )
    pct_eff = effective_parts_pct(part, directory)
    dirrow = directory["by_user"].get(part.user_id)
    snap = await entreprise_snapshot(db, part.entreprise_id)
    valeur_parts = round(snap["equite"] * pct_eff / 100.0, 2)
    k = kpis_participation(flux, valeur_parts)
    return {
        "id": part.id,
        "entreprise_id": part.entreprise_id,
        "user_id": part.user_id,
        "user_name": (
            dirrow["name"] if dirrow else (_user_display(u) if u else "—")
        ),
        "user_email": u.email if u else None,
        "parts_pct": pct_eff,
        "parts_source": "fiche" if dirrow else "manuel",
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


# ───────────────────── Vue globale (portefeuille) ─────────────────────


@router.get(
    "/portefeuille-global",
    summary="Vue globale : TOUS les investissements, toutes compagnies",
)
async def portefeuille_global(db: DBSession, user: CurrentUser) -> dict:
    """Même forme que /invest/me/portefeuille, mais agrégée sur TOUTES
    les participations (visibles ou non) — la vue direction. Chaque
    carte projet montre le total des parts investisseurs, le cash-flow
    COMPLET de la compagnie et le TRI combiné des investisseurs."""
    parts = (
        await db.execute(
            select(InvestParticipation).order_by(
                InvestParticipation.entreprise_id, InvestParticipation.id
            )
        )
    ).scalars().all()

    by_ent: dict[int, list[InvestParticipation]] = {}
    for p in parts:
        by_ent.setdefault(p.entreprise_id, []).append(p)

    pairs: list[tuple[InvestParticipation, list[InvestFlux]]] = []
    projets: list[dict] = []
    tot_capital_actuel = tot_capital_total = 0.0
    tot_rembourse = tot_distrib = tot_valeur_parts = 0.0
    flux_global: list = []
    from datetime import date as _date

    for eid, plist in by_ent.items():
        ent = await db.get(Entreprise, eid)
        if ent is None:
            continue
        snap = await entreprise_snapshot(db, eid)
        directory = await partner_directory(db, eid)
        flux_combined: list[InvestFlux] = []
        pct_total = 0.0
        for p in plist:
            fl = list(
                (
                    await db.execute(
                        select(InvestFlux)
                        .where(InvestFlux.participation_id == p.id)
                        .order_by(InvestFlux.date_flux, InvestFlux.id)
                    )
                ).scalars()
            )
            flux_combined.extend(fl)
            pairs.append((p, fl))
            pct_total += effective_parts_pct(p, directory)
        valeur_parts = round(snap["equite"] * pct_total / 100.0, 2)
        k = kpis_participation(flux_combined, valeur_parts)
        profil = await get_or_default_profil(db, eid)
        phase = await phase_projet(db, eid, profil)
        serie = await serie_mensuelle(db, eid, months=12)
        adresses = [i["address"] or i["name"] for i in snap["immeubles"]]
        projets.append(
            {
                "entreprise_id": eid,
                "entreprise_name": ent.name,
                "color_accent": ent.color_accent,
                "phase": phase,
                "adresse": adresses[0] if adresses else None,
                "nb_immeubles": len(snap["immeubles"]),
                "nb_logements": snap["nb_logements"],
                "cover_photo_url": (
                    snap["immeubles"][0]["cover_photo_url"]
                    if snap["immeubles"]
                    else None
                ),
                "parts_pct": round(pct_total, 3),
                "valeur_parts": valeur_parts,
                # Vue direction : cash-flow COMPLET de la compagnie.
                "cashflow_moyen_part": serie["cashflow_moyen"],
                "statut": "actif",
                "nb_investisseurs": len(plist),
                **k,
            }
        )
        tot_capital_actuel += k["capital_actuel"]
        tot_capital_total += k["capital_investi_total"]
        tot_rembourse += k["capital_rembourse"]
        tot_distrib += k["distributions_recues"]
        tot_valeur_parts += valeur_parts
        flux_global.extend(flux_signes(flux_combined))
        if valeur_parts:
            flux_global.append((_date.today(), valeur_parts))

    tri_global = xirr(flux_global)
    return {
        "capital_actuel": round(tot_capital_actuel, 2),
        "capital_investi_total": round(tot_capital_total, 2),
        "capital_rembourse": round(tot_rembourse, 2),
        "distributions_recues": round(tot_distrib, 2),
        "valeur_parts": round(tot_valeur_parts, 2),
        "tri_pct": round(tri_global * 100, 1)
        if tri_global is not None
        else None,
        "tvpi": (
            round(
                (tot_rembourse + tot_distrib + tot_valeur_parts)
                / tot_capital_total,
                4,
            )
            if tot_capital_total > 0
            else None
        ),
        "serie_valeur": await serie_valeur_totale(db, pairs),
        "projets": projets,
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
        directory = await partner_directory(db, ent.id)
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
            dirrow = directory["by_user"].get(p.user_id)
            investisseurs.append(
                {
                    "participation_id": p.id,
                    "user_id": p.user_id,
                    "name": (
                        dirrow["name"]
                        if dirrow
                        else (_user_display(u) if u else "—")
                    ),
                    "parts_pct": effective_parts_pct(p, directory),
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
    directory = await partner_directory(db, entreprise_id)
    parts = (
        await db.execute(
            select(InvestParticipation)
            .where(InvestParticipation.entreprise_id == entreprise_id)
            .order_by(InvestParticipation.id)
        )
    ).scalars().all()
    participations = [
        await _participation_payload(db, p, directory) for p in parts
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

    # Actionnaires « Parts & actionnaires » de la compagnie (pôle
    # gestion d'entreprise) — la SOURCE des investisseurs du projet.
    # L'admin n'a plus qu'à « Activer » puis « Rendre visible ».
    part_by_user = {p.user_id: p for p in parts}
    partenaires: list[dict] = []
    partner_rows = (
        await db.execute(
            select(EntreprisePartner)
            .where(EntreprisePartner.entreprise_id == entreprise_id)
            .order_by(EntreprisePartner.id)
        )
    ).scalars().all()
    for pr in partner_rows:
        pu = await _resolve_partner_user(db, pr)
        name, email = _partner_identity(pr, pu)
        linked = part_by_user.get(pu.id) if pu else None
        partenaires.append(
            {
                "partner_id": pr.id,
                "name": name,
                "email": email,
                "missing_email": not email,
                "role": pr.role,
                "ownership_pct": (
                    float(pr.ownership_pct)
                    if pr.ownership_pct is not None
                    else None
                ),
                "user_id": pu.id if pu else None,
                "has_account": pu is not None,
                "deja_participant": linked is not None,
                "participation_id": linked.id if linked else None,
                "is_visible": linked.is_visible if linked else False,
            }
        )

    # Dossier Drive de la compagnie : le MÊME que la section Documents
    # Drive de la fiche entreprise (DriveEntityLink), avec repli sur
    # l'URL saisie manuellement dans la fiche.
    from app.models.drive_entity_link import DriveEntityLink

    drive_link = (
        await db.execute(
            select(DriveEntityLink).where(
                DriveEntityLink.entity_type == "Entreprise",
                DriveEntityLink.entity_id == entreprise_id,
            )
        )
    ).scalar_one_or_none()

    return {
        "entreprise_id": ent.id,
        "name": ent.name,
        "color_accent": ent.color_accent,
        "drive_folder_id": (
            drive_link.drive_folder_id
            if drive_link
            else _drive_folder_id(ent.drive_folder_url)
        ),
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
            "avances_actionnaires": (
                float(profil.avances_actionnaires)
                if profil is not None
                and profil.avances_actionnaires is not None
                else None
            ),
        },
        **snap,
        "serie_mensuelle": serie["rows"],
        "revenus_mode": serie["revenus_mode"],
        "depenses_par_categorie": serie["depenses_par_categorie"],
        "hypotheque_mensuelle": serie["hypotheque_mensuelle"],
        "cashflow_moyen": serie["cashflow_moyen"],
        "participations": participations,
        "partenaires": partenaires,
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
    if "avances_actionnaires" in data.model_fields_set:
        profil.avances_actionnaires = data.avances_actionnaires or None
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

    _ensure_volet_investisseur(target_user)
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


# ─────────────── Réels QuickBooks (section optimisation) ───────────────


@router.get(
    "/projets/{entreprise_id}/qbo-reels",
    summary="Revenus/dépenses RÉELS (QuickBooks via le projet "
    "d'optimisation de la compagnie) — 12 derniers mois",
)
async def qbo_reels(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> dict:
    """Statuts : aucun_projet | sans_qbo | erreur | connecte — depuis
    l'ouverture du projet d'optimisation (le frontend filtre par
    année)."""
    await _load_entreprise(db, entreprise_id)
    return await qbo_reels_data(db, entreprise_id)


# ───────── Synchronisation QuickBooks (avances d'actionnaires) ─────────


_MOIS_TOKENS = {
    # anglais (libellés de colonnes QBO par défaut)
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    # français
    "janv": 1, "fevr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6,
    "juil": 7, "aout": 8, "sept": 9, "octo": 10, "nove": 11, "dece": 12,
}


def _parse_mois_qbo(label: str) -> Optional[date]:
    """« Jul 2025 » / « juil. 2025 » → date(2025, 7, 1). None si le
    libellé ne ressemble pas à un mois."""
    import unicodedata

    m = re.search(r"([A-Za-zÀ-ÿ]+)\.?\s+(\d{4})", label or "")
    if not m:
        return None
    tok = "".join(
        c
        for c in unicodedata.normalize("NFD", m.group(1).lower())
        if unicodedata.category(c) != "Mn"
    )
    for prefix, num in _MOIS_TOKENS.items():
        if tok.startswith(prefix) or (
            len(tok) >= 3 and prefix.startswith(tok)
        ):
            return date(int(m.group(2)), num, 1)
    return None


def _norm_nom(s: str) -> str:
    import unicodedata

    s = "".join(
        c
        for c in unicodedata.normalize("NFD", (s or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@router.post(
    "/projets/{entreprise_id}/sync-qbo",
    summary="Synchronise les avances d'actionnaires QuickBooks : "
    "équité + flux (apports/remboursements) par investisseur",
)
async def sync_qbo_avances(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> dict:
    """Lecture des comptes « avances d'actionnaires » du QuickBooks lié
    au projet d'optimisation de la compagnie :

    1. le TOTAL des avances remplace `profil.avances_actionnaires`
       (équité = valeur − hypothèques − avances) ;
    2. chaque compte est apparié à un investisseur par NOM (fiche
       entreprise / compte) ; ses variations mensuelles deviennent des
       flux `source=qbo` (hausse = apport, baisse = remboursement) —
       les flux qbo précédents sont remplacés, les flux manuels ne sont
       pas touchés. Aucune double saisie."""
    await _load_entreprise(db, entreprise_id)
    p, premier = await optimisation_projet_qbo(db, entreprise_id)
    if premier is None:
        return {"statut": "aucun_projet"}
    if p is None:
        return {"statut": "sans_qbo", "projet_nom": premier.name}

    from app.services.qbo_optimisation import avances_actionnaires

    try:
        av = await avances_actionnaires(
            p.qbo_scope,
            (p.date_debut or date(2000, 1, 1)).isoformat(),
            date.today().isoformat(),
            p.avances_accounts_json,
        )
    except Exception as exc:  # noqa: BLE001 — message propre à l'UI
        log.info("invest sync-qbo entreprise #%s: %s", entreprise_id, exc)
        return {
            "statut": "erreur",
            "projet_nom": p.name,
            "erreur": str(exc)[:300],
        }

    comptes = av.get("comptes") or []
    total = float(av.get("total") or 0.0)

    # 1. Avances totales → profil (équité).
    profil = await get_or_default_profil(db, entreprise_id)
    if profil is None:
        profil = InvestProjetProfil(entreprise_id=entreprise_id)
        db.add(profil)
        await db.flush()
    profil.avances_actionnaires = round(total, 2)

    # 2. Appariement compte ↔ investisseur par nom.
    directory = await partner_directory(db, entreprise_id)
    parts = (
        await db.execute(
            select(InvestParticipation)
            .where(InvestParticipation.entreprise_id == entreprise_id)
            .order_by(InvestParticipation.id)
        )
    ).scalars().all()
    candidats: list[tuple[InvestParticipation, set[str]]] = []
    for part in parts:
        noms: set[str] = set()
        dirrow = directory["by_user"].get(part.user_id)
        if dirrow:
            noms.add(_norm_nom(dirrow["name"]))
        u = await db.get(User, part.user_id)
        if u:
            noms.add(_norm_nom(f"{u.first_name or ''} {u.last_name or ''}"))
            if u.last_name and len(u.last_name) > 3:
                noms.add(_norm_nom(u.last_name))
        candidats.append((part, {n for n in noms if len(n) > 3}))

    apparies: list[dict] = []
    non_apparies: list[str] = []
    for compte in comptes:
        nom_compte = _norm_nom(str(compte.get("nom") or ""))
        matches = [
            part
            for part, noms in candidats
            if any(n in nom_compte or nom_compte in n for n in noms)
        ]
        if len(matches) != 1:
            non_apparies.append(str(compte.get("nom") or "?"))
            continue
        part = matches[0]

        # Remplace les flux qbo de cette participation (idempotent).
        anciens = (
            await db.execute(
                select(InvestFlux).where(
                    InvestFlux.participation_id == part.id,
                    InvestFlux.source == "qbo",
                )
            )
        ).scalars().all()
        for f in anciens:
            await db.delete(f)

        nb = 0
        mois_rows = compte.get("mois") or []
        # Solde AVANT le premier mois affiché = apport initial (compte
        # ouvert avant la période demandée).
        if mois_rows:
            r0 = mois_rows[0]
            initial = float(r0.get("solde") or 0) - float(
                r0.get("variation") or 0
            )
            d0 = _parse_mois_qbo(str(r0.get("mois") or ""))
            if abs(initial) > 0.005 and d0 is not None:
                db.add(
                    InvestFlux(
                        participation_id=part.id,
                        type=(
                            InvestFluxType.APPORT.value
                            if initial > 0
                            else InvestFluxType.REMBOURSEMENT.value
                        ),
                        montant=round(abs(initial), 2),
                        date_flux=d0,
                        note=f"QBO · {compte.get('nom')} (solde initial)",
                        source="qbo",
                    )
                )
                nb += 1
        for r in mois_rows:
            variation = float(r.get("variation") or 0)
            if abs(variation) < 0.005:
                continue
            d = _parse_mois_qbo(str(r.get("mois") or ""))
            if d is None:
                continue
            db.add(
                InvestFlux(
                    participation_id=part.id,
                    type=(
                        InvestFluxType.APPORT.value
                        if variation > 0
                        else InvestFluxType.REMBOURSEMENT.value
                    ),
                    montant=round(abs(variation), 2),
                    date_flux=d,
                    note=f"QBO · {compte.get('nom')}",
                    source="qbo",
                )
            )
            nb += 1
        dirrow = directory["by_user"].get(part.user_id)
        apparies.append(
            {
                "compte": compte.get("nom"),
                "solde": compte.get("solde"),
                "participation_id": part.id,
                "investisseur": (
                    dirrow["name"] if dirrow else str(part.user_id)
                ),
                "nb_flux": nb,
            }
        )

    await db.flush()
    await db.commit()
    return {
        "statut": "ok",
        "projet_nom": p.name,
        "avances_total": round(total, 2),
        "apparies": apparies,
        "non_apparies": non_apparies,
    }


# ─────────── Activation d'un actionnaire (depuis un projet) ───────────


@router.post(
    "/projets/{entreprise_id}/partenaires/{partner_id}/activer",
    summary="Active un actionnaire comme investisseur du projet "
    "(compte + participation invisible, créés au besoin)",
)
async def activer_partenaire(
    entreprise_id: int,
    partner_id: int,
    db: DBSession,
    user: CurrentUser,
) -> dict:
    await _load_entreprise(db, entreprise_id)
    pr = await db.get(EntreprisePartner, partner_id)
    if pr is None or pr.entreprise_id != entreprise_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Actionnaire introuvable."
        )
    pu = await _resolve_partner_user(db, pr)
    invitation_sent = False
    temp_password: Optional[str] = None
    if pu is None:
        name, email = _partner_identity(pr, None)
        if not email:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Courriel manquant pour {name} — ajoutez-le dans la "
                "fiche entreprise (Parts & actionnaires).",
            )
        first, last = _split_name(name)
        pu, _created, invitation_sent, temp_password = (
            await _create_investor_account(
                db,
                first_name=first,
                last_name=last,
                email=email,
                phone=pr.partner_telephone,
                invited_by=user.email,
            )
        )
    _ensure_volet_investisseur(pu)
    part, _ = await _ensure_participation(
        db,
        pu.id,
        entreprise_id,
        float(pr.ownership_pct) if pr.ownership_pct is not None else None,
    )
    await db.commit()
    payload = await _participation_payload(db, part)
    payload["invitation_sent"] = invitation_sent
    payload["temp_password"] = temp_password
    return payload


# ─────────────────────── Investisseurs (comptes) ───────────────────────


@router.get(
    "/investisseurs",
    summary="Tous les actionnaires de tous les projets (+ comptes)",
)
async def list_investisseurs(db: DBSession, user: CurrentUser) -> List[dict]:
    """Union des actionnaires « Parts & actionnaires » de toutes les
    compagnies ET des participations existantes — dédupliqués par
    compte/courriel. C'est ici qu'on voit qui a son compte (✓) et
    qu'on envoie les informations de création."""
    ents = {
        e.id: e
        for e in (
            await db.execute(select(Entreprise))
        ).scalars().all()
    }
    parts = (
        await db.execute(select(InvestParticipation))
    ).scalars().all()
    parts_by_user: dict[int, list[InvestParticipation]] = {}
    for p in parts:
        parts_by_user.setdefault(p.user_id, []).append(p)

    groups: dict[str, dict] = {}

    def _group_for(
        key: str, name: str, email: Optional[str], pu: Optional[User]
    ) -> dict:
        g = groups.get(key)
        if g is None:
            g = {
                "key": key,
                "name": name,
                "email": email,
                "missing_email": not email,
                "user_id": pu.id if pu else None,
                "has_account": pu is not None,
                "role": pu.role if pu else None,
                "is_active": pu.is_active if pu else None,
                "must_change_password": (
                    pu.must_change_password if pu else None
                ),
                "partner_id": None,
                "entreprises": [],
                "nb_projets_visibles": 0,
            }
            groups[key] = g
        return g

    # 1) Actionnaires de toutes les compagnies (fiche entreprise).
    partner_rows = (
        await db.execute(
            select(EntreprisePartner).order_by(EntreprisePartner.id)
        )
    ).scalars().all()
    for pr in partner_rows:
        ent = ents.get(pr.entreprise_id)
        if ent is None or not ent.is_active:
            continue
        pu = await _resolve_partner_user(db, pr)
        name, email = _partner_identity(pr, pu)
        key = (
            f"user:{pu.id}"
            if pu
            else (f"email:{email}" if email else f"partner:{pr.id}")
        )
        g = _group_for(key, name, email, pu)
        if g["partner_id"] is None:
            g["partner_id"] = pr.id
        if all(e["id"] != ent.id for e in g["entreprises"]):
            g["entreprises"].append(
                {
                    "id": ent.id,
                    "name": ent.name,
                    "pct": (
                        float(pr.ownership_pct)
                        if pr.ownership_pct is not None
                        else None
                    ),
                }
            )

    # 2) Participations sans ligne d'actionnaire (ajouts manuels).
    for uid, plist in parts_by_user.items():
        pu = await db.get(User, uid)
        if pu is None:
            continue
        key = f"user:{uid}"
        g = _group_for(key, _user_display(pu), pu.email, pu)
        for p in plist:
            ent = ents.get(p.entreprise_id)
            if ent and all(e["id"] != ent.id for e in g["entreprises"]):
                g["entreprises"].append(
                    {"id": ent.id, "name": ent.name, "pct": float(p.parts_pct)}
                )
        g["nb_projets_visibles"] = sum(1 for p in plist if p.is_visible)

    out = list(groups.values())
    out.sort(key=lambda g: (not g["has_account"], g["name"].lower()))
    return out


@router.post(
    "/partenaires/{partner_id}/creer-compte",
    summary="Crée le compte d'un actionnaire + participations "
    "(invisibles) dans toutes ses compagnies, et envoie l'invitation",
)
async def creer_compte_partenaire(
    partner_id: int, db: DBSession, user: CurrentUser
) -> dict:
    pr = await db.get(EntreprisePartner, partner_id)
    if pr is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Actionnaire introuvable."
        )
    pu = await _resolve_partner_user(db, pr)
    name, email = _partner_identity(pr, pu)
    invitation_sent = False
    temp_password: Optional[str] = None
    if pu is None:
        if not email:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Courriel manquant pour {name} — ajoutez-le dans la "
                "fiche entreprise (Parts & actionnaires).",
            )
        first, last = _split_name(name)
        pu, _created, invitation_sent, temp_password = (
            await _create_investor_account(
                db,
                first_name=first,
                last_name=last,
                email=email,
                phone=pr.partner_telephone,
                invited_by=user.email,
            )
        )
    _ensure_volet_investisseur(pu)
    # Participations INVISIBLES dans toutes les compagnies où cette
    # personne est actionnaire (même user ou même courriel) — le compte
    # démarre avec 0 projet visible ; « Rendre visible » se fait
    # projet par projet.
    all_rows = (
        await db.execute(
            select(EntreprisePartner).order_by(EntreprisePartner.id)
        )
    ).scalars().all()
    nb_crees = 0
    for row in all_rows:
        row_user = await _resolve_partner_user(db, row)
        _n, row_email = _partner_identity(row, row_user)
        same = (row_user is not None and row_user.id == pu.id) or (
            email and row_email and row_email == email
        )
        if not same:
            continue
        _part, created = await _ensure_participation(
            db,
            pu.id,
            row.entreprise_id,
            float(row.ownership_pct)
            if row.ownership_pct is not None
            else None,
        )
        if created:
            nb_crees += 1
    await db.commit()
    return {
        "user_id": pu.id,
        "invitation_sent": invitation_sent,
        "temp_password": temp_password,
        "participations_creees": nb_crees,
    }


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
    if target.role in ("owner", "admin"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Compte direction — gérez-le dans Utilisateurs & rôles.",
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


@router.post(
    "/investisseurs/{user_id}/toggle-active",
    summary="Désactive / réactive l'accès d'un investisseur",
)
async def toggle_investor_active(
    user_id: int, db: DBSession, user: CurrentUser
) -> dict:
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Utilisateur introuvable."
        )
    if target.role in ("owner", "admin"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Compte direction — gérez-le dans Utilisateurs & rôles.",
        )
    if target.id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Impossible de désactiver son propre compte.",
        )
    target.is_active = not bool(target.is_active)
    await db.flush()
    await db.commit()
    return {"is_active": target.is_active}


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
