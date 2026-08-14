"""Portail Investisseur v2 — endpoints CÔTÉ INVESTISSEUR (lecture seule).

    GET /invest/me/portefeuille               vue d'ensemble
    GET /invest/me/projets/{entreprise_id}    fiche projet
    GET /invest/me/documents/{doc_id}/pdf     document partagé

Un investisseur ne voit QUE les compagnies où il a une participation
`is_visible`. Les assembleurs `build_portefeuille` / `build_projet`
sont partagés avec la console admin (« voir comme lui »).

Registered avec DEP_INVESTISSEUR (volet investisseur).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.api.deps import CurrentUser, DBSession
from app.models.entreprise import Entreprise
from app.models.invest_portal import (
    InvestDocument,
    InvestFlux,
    InvestParticipation,
)
from app.models.user import User
from app.services.invest_portfolio import (
    entreprise_snapshot,
    flux_signes,
    get_or_default_profil,
    kpis_participation,
    phase_projet,
    serie_mensuelle,
    serie_valeur_totale,
    timeline_projet,
)
from app.services.invest_tri import xirr

log = logging.getLogger(__name__)

router = APIRouter(prefix="/invest", tags=["invest-portal"])


# ─────────────────────────────────────────────────────────────────────
# Assembleurs (partagés avec la console admin)
# ─────────────────────────────────────────────────────────────────────


async def _participations_visibles(
    db: AsyncSession, user_id: int
) -> list[InvestParticipation]:
    return list(
        (
            await db.execute(
                select(InvestParticipation)
                .where(
                    InvestParticipation.user_id == user_id,
                    InvestParticipation.is_visible.is_(True),
                )
                .order_by(InvestParticipation.id)
            )
        ).scalars()
    )


async def _flux_of(
    db: AsyncSession, participation_id: int
) -> list[InvestFlux]:
    return list(
        (
            await db.execute(
                select(InvestFlux)
                .where(InvestFlux.participation_id == participation_id)
                .order_by(InvestFlux.date_flux, InvestFlux.id)
            )
        ).scalars()
    )


async def build_portefeuille(db: AsyncSession, user_id: int) -> dict:
    parts = await _participations_visibles(db, user_id)
    pairs: list[tuple[InvestParticipation, list[InvestFlux]]] = []
    projets: list[dict] = []
    tot_capital_actuel = 0.0
    tot_capital_total = 0.0
    tot_retours = 0.0
    tot_valeur_parts = 0.0
    flux_global: list[tuple[date, float]] = []

    for part in parts:
        ent = await db.get(Entreprise, part.entreprise_id)
        if ent is None:
            continue
        flux = await _flux_of(db, part.id)
        pairs.append((part, flux))
        snap = await entreprise_snapshot(db, part.entreprise_id)
        pct = float(part.parts_pct) / 100.0
        valeur_parts = round(snap["equite"] * pct, 2)
        k = kpis_participation(flux, valeur_parts)
        profil = await get_or_default_profil(db, part.entreprise_id)
        phase = await phase_projet(db, part.entreprise_id, profil)
        serie = await serie_mensuelle(db, part.entreprise_id)
        show_cashflow = profil.show_cashflow if profil else True
        cash_part = (
            round(serie["cashflow_moyen"] * pct, 2)
            if show_cashflow
            else None
        )
        adresses = [
            i["address"] or i["name"] for i in snap["immeubles"]
        ]
        projets.append(
            {
                "entreprise_id": part.entreprise_id,
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
                "parts_pct": float(part.parts_pct),
                "valeur_parts": valeur_parts,
                "cashflow_moyen_part": cash_part,
                "statut": part.statut,
                **k,
            }
        )
        tot_capital_actuel += k["capital_actuel"]
        tot_capital_total += k["capital_investi_total"]
        tot_retours += k["capital_rembourse"] + k["distributions_recues"]
        tot_valeur_parts += valeur_parts
        flux_global.extend(flux_signes(flux))
        if valeur_parts:
            flux_global.append((date.today(), valeur_parts))

    tri_global = xirr(flux_global)
    tvpi_global = (
        round((tot_retours + tot_valeur_parts) / tot_capital_total, 4)
        if tot_capital_total > 0
        else None
    )
    serie_valeur = await serie_valeur_totale(db, pairs)

    return {
        "capital_actuel": round(tot_capital_actuel, 2),
        "capital_investi_total": round(tot_capital_total, 2),
        "capital_rembourse": round(
            sum(p["capital_rembourse"] for p in projets), 2
        ),
        "distributions_recues": round(
            sum(p["distributions_recues"] for p in projets), 2
        ),
        "valeur_parts": round(tot_valeur_parts, 2),
        "tri_pct": round(tri_global * 100, 1)
        if tri_global is not None
        else None,
        "tvpi": tvpi_global,
        "serie_valeur": serie_valeur,
        "projets": projets,
    }


async def build_projet(
    db: AsyncSession, user_id: int, entreprise_id: int
) -> dict:
    part = (
        await db.execute(
            select(InvestParticipation).where(
                InvestParticipation.user_id == user_id,
                InvestParticipation.entreprise_id == entreprise_id,
                InvestParticipation.is_visible.is_(True),
            )
        )
    ).scalar_one_or_none()
    if part is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Projet introuvable."
        )
    ent = await db.get(Entreprise, entreprise_id)
    if ent is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Projet introuvable."
        )

    profil = await get_or_default_profil(db, entreprise_id)
    show_depenses = profil.show_depenses if profil else True
    show_hypotheque = profil.show_hypotheque if profil else True
    show_actionnaires = profil.show_actionnaires if profil else True
    show_cashflow = profil.show_cashflow if profil else True

    snap = await entreprise_snapshot(db, entreprise_id)
    pct = float(part.parts_pct) / 100.0
    valeur_parts = round(snap["equite"] * pct, 2)
    flux = await _flux_of(db, part.id)
    k = kpis_participation(flux, valeur_parts)
    phase = await phase_projet(db, entreprise_id, profil)
    serie = await serie_mensuelle(db, entreprise_id)
    timeline = await timeline_projet(db, entreprise_id, flux, phase)

    # Co-actionnaires de CETTE compagnie (jamais les autres projets).
    # Le nom saisi dans « Parts & actionnaires » (fiche entreprise)
    # PRIME sur le nom du compte : c'est souvent un holding (« Groupe X
    # Investissement ») dont le compte de connexion reste la personne.
    actionnaires: list[dict] = []
    if show_actionnaires:
        from app.models.entreprise import EntreprisePartner

        override_by_user: dict[int, str] = {}
        override_by_email: dict[str, str] = {}
        for pr in (
            await db.execute(
                select(EntreprisePartner).where(
                    EntreprisePartner.entreprise_id == entreprise_id
                )
            )
        ).scalars():
            nm = (pr.partner_name or "").strip()
            if not nm:
                continue
            if pr.user_id:
                override_by_user[pr.user_id] = nm
            if pr.partner_email:
                override_by_email[pr.partner_email.strip().lower()] = nm

        all_parts = (
            await db.execute(
                select(InvestParticipation, User)
                .join(User, User.id == InvestParticipation.user_id)
                .where(
                    InvestParticipation.entreprise_id == entreprise_id,
                    InvestParticipation.statut == "actif",
                )
                .order_by(InvestParticipation.parts_pct.desc())
            )
        ).all()
        total_pct = 0.0
        for p, u in all_parts:
            name = (
                override_by_user.get(u.id)
                or override_by_email.get((u.email or "").lower())
                or f"{u.first_name or ''} {u.last_name or ''}".strip()
                or u.email
            )
            actionnaires.append(
                {
                    "name": name,
                    "parts_pct": float(p.parts_pct),
                    "is_me": u.id == user_id,
                }
            )
            total_pct += float(p.parts_pct)
        reste = round(100.0 - total_pct, 3)
        if reste > 0.01:
            actionnaires.append(
                {
                    "name": "Groupe Horizon",
                    "parts_pct": reste,
                    "is_me": False,
                }
            )

    docs = (
        await db.execute(
            select(InvestDocument)
            .where(InvestDocument.entreprise_id == entreprise_id)
            .order_by(InvestDocument.id.desc())
        )
    ).scalars().all()

    immeubles = snap["immeubles"]
    for i in immeubles:
        # Détail par logement réservé à la console admin.
        i.pop("logements", None)
    if not show_hypotheque:
        for i in immeubles:
            i["hypotheque_preteur"] = None
            i["hypotheque_taux_pct"] = None
            i["hypotheque_fin_terme"] = None

    serie_rows = serie["rows"]
    if not show_depenses:
        serie_rows = [
            {**r, "depenses": None} for r in serie_rows
        ]

    labels_flux = {
        "apport": "Apport de capital",
        "remboursement": "Remboursement de capital",
        "dividende": "Distribution",
        "sortie": "Sortie",
    }

    return {
        "entreprise_id": entreprise_id,
        "entreprise_name": ent.name,
        "description": profil.description if profil else None,
        "phase": phase,
        "statut_participation": part.statut,
        "immeubles": immeubles,
        "valeur_totale": snap["valeur_totale"],
        "hypotheque_totale": snap["hypotheque_totale"],
        "avances_actionnaires": snap["avances_actionnaires"],
        "equite": snap["equite"],
        "loyers_mensuels": snap["loyers_mensuels"],
        "nb_logements": snap["nb_logements"],
        "nb_baux_actifs": snap["nb_baux_actifs"],
        "taux_occupation": snap["taux_occupation"],
        "serie_mensuelle": serie_rows,
        "revenus_mode": serie["revenus_mode"],
        "depenses_par_categorie": (
            serie["depenses_par_categorie"] if show_depenses else []
        ),
        "hypotheque_mensuelle": (
            serie["hypotheque_mensuelle"] if show_hypotheque else None
        ),
        "cashflow_moyen": (
            serie["cashflow_moyen"] if show_cashflow else None
        ),
        "timeline": timeline,
        "parts_pct": float(part.parts_pct),
        "valeur_parts": valeur_parts,
        **k,
        "flux": [
            {
                "id": f.id,
                "type": f.type,
                "label": labels_flux.get(f.type, f.type),
                "montant": float(f.montant),
                "date_flux": f.date_flux.isoformat(),
                "note": f.note,
            }
            for f in flux
        ],
        "actionnaires": actionnaires,
        "show_depenses": show_depenses,
        "show_hypotheque": show_hypotheque,
        "show_actionnaires": show_actionnaires,
        "show_cashflow": show_cashflow,
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "size_bytes": d.size_bytes,
                "created_at": d.created_at.isoformat()
                if d.created_at
                else None,
            }
            for d in docs
        ],
    }


# ─────────────────────────────────────────────────────────────────────
# Routes investisseur
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/me/portefeuille",
    summary="Vue d'ensemble du portefeuille de l'investisseur connecté",
)
async def my_portefeuille(db: DBSession, user: CurrentUser) -> dict:
    return await build_portefeuille(db, user.id)


@router.get(
    "/me/projets/{entreprise_id}",
    summary="Fiche projet (compagnie) de l'investisseur connecté",
)
async def my_projet(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> dict:
    return await build_projet(db, user.id, entreprise_id)


@router.get(
    "/me/releve/{year}/pdf",
    summary="Relevé annuel PDF de l'investisseur connecté",
)
async def my_releve_pdf(
    year: int, db: DBSession, user: CurrentUser
) -> Response:
    if year < 2000 or year > date.today().year:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Année invalide."
        )
    from app.services.invest_releve_pdf import build_releve_pdf

    portefeuille = await build_portefeuille(db, user.id)
    pdf = await build_releve_pdf(db, user, year, portefeuille)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'inline; filename="Releve annuel {year}.pdf"'
        },
    )


@router.get(
    "/me/documents/{doc_id}/pdf",
    summary="Document partagé (PDF inline)",
)
async def my_document_pdf(
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
    part = (
        await db.execute(
            select(InvestParticipation.id).where(
                InvestParticipation.user_id == user.id,
                InvestParticipation.entreprise_id == doc.entreprise_id,
                InvestParticipation.is_visible.is_(True),
            )
        )
    ).scalar_one_or_none()
    if part is None:
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
