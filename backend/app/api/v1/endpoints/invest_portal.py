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
from app.services.invest_portfolio import (
    avances_par_actionnaire,
    effective_parts_pct,
    entreprise_snapshot,
    flux_signes,
    get_or_default_profil,
    kpis_participation,
    partner_directory,
    phase_projet,
    qbo_piece_data,
    qbo_reels_data,
    qbo_txns_compte_data,
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
        directory = await partner_directory(db, part.entreprise_id)
        pct_eff = effective_parts_pct(part, directory)
        pct = pct_eff / 100.0
        valeur_parts = round(snap["equite"] * pct, 2)
        k = kpis_participation(flux, valeur_parts)
        profil = await get_or_default_profil(db, part.entreprise_id)
        phase = await phase_projet(db, part.entreprise_id, profil)
        serie = await serie_mensuelle(db, part.entreprise_id, months=12)
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
                "parts_pct": pct_eff,
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
    directory = await partner_directory(db, entreprise_id)
    pct_eff = effective_parts_pct(part, directory)
    pct = pct_eff / 100.0
    valeur_parts = round(snap["equite"] * pct, 2)
    flux = await _flux_of(db, part.id)
    k = kpis_participation(flux, valeur_parts)
    phase = await phase_projet(db, entreprise_id, profil)
    serie = await serie_mensuelle(db, entreprise_id)
    timeline = await timeline_projet(db, entreprise_id, flux, phase)

    # Co-actionnaires de CETTE compagnie : la liste RÉELLE de « Parts &
    # actionnaires » (fiche entreprise) — noms et % tels que saisis là,
    # jamais de ligne inventée. `is_me` = l'actionnaire apparié au
    # compte connecté.
    actionnaires: list[dict] = []
    if show_actionnaires:
        for row in directory["rows"]:
            actionnaires.append(
                {
                    "name": row["name"],
                    "parts_pct": row["ownership_pct"],
                    "is_me": row["user_id"] == user_id,
                }
            )
        actionnaires.sort(
            key=lambda a: -(a["parts_pct"] or 0.0)
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
            i["hypotheques"] = []

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
        "parts_pct": pct_eff,
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
        # La sync QBO (avances d'actionnaires) a-t-elle déjà tourné ?
        # Tant que non, un capital à 0 = « pas encore de données » ;
        # après, il veut dire « remboursé complètement ».
        "apports_synchronises": bool(
            profil is not None and profil.qbo_sync_at is not None
        ),
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
    "/me/projets/{entreprise_id}/qbo-reels",
    summary="Revenus/dépenses RÉELS (QuickBooks) du projet — investisseur",
)
async def my_projet_qbo_reels(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> dict:
    """Même série que la console admin, pour un projet où
    l'investisseur a une participation visible. Respecte les réglages
    de publication : masqué si `show_cashflow` est décoché ; le détail
    par compte est retiré si `show_depenses` est décoché."""
    part = (
        await db.execute(
            select(InvestParticipation.id).where(
                InvestParticipation.user_id == user.id,
                InvestParticipation.entreprise_id == entreprise_id,
                InvestParticipation.is_visible.is_(True),
            )
        )
    ).scalar_one_or_none()
    if part is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Projet introuvable."
        )
    profil = await get_or_default_profil(db, entreprise_id)
    if profil is not None and not profil.show_cashflow:
        return {"statut": "masque"}
    data = await qbo_reels_data(db, entreprise_id)
    if profil is not None and not profil.show_depenses:
        for r in data.get("rows") or []:
            r.pop("details", None)
        if isinstance(data.get("total"), dict):
            data["total"].pop("details", None)
    return data


async def _ma_participation_ou_404(
    db: AsyncSession, user_id: int, entreprise_id: int
) -> None:
    """Garde des routes de détail QBO : participation visible requise,
    et les interrupteurs de publication du projet respectés (pas de
    détail des dépenses si l'admin les masque)."""
    part = (
        await db.execute(
            select(InvestParticipation.id).where(
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
    profil = await get_or_default_profil(db, entreprise_id)
    if profil is not None and (
        not profil.show_cashflow or not profil.show_depenses
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Projet introuvable."
        )


@router.get(
    "/me/projets/{entreprise_id}/qbo-comptes/{compte_id}/transactions",
    summary="Transactions d'un compte de dépense (mois cliqué) — "
    "investisseur",
)
async def my_projet_qbo_txns(
    entreprise_id: int,
    compte_id: str,
    debut: str,
    fin: str,
    db: DBSession,
    user: CurrentUser,
) -> list:
    """Clic sur un compte du tableau « Revenus et dépenses réels » :
    transactions QuickBooks de CE compte pour CE mois, avec leurs
    factures jointes — même principe que la page Optimisation (demande
    Phil 2026-08-25)."""
    await _ma_participation_ou_404(db, user.id, entreprise_id)
    # Les dates sont interpolées dans la requête QuickBooks : jamais de
    # texte libre.
    try:
        d1 = date.fromisoformat(debut)
        d2 = date.fromisoformat(fin)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Dates attendues au format AAAA-MM-JJ.",
        )
    if not compte_id.isdigit():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Compte invalide."
        )
    try:
        return await qbo_txns_compte_data(
            db, entreprise_id, compte_id, d1.isoformat(), d2.isoformat()
        )
    except Exception as exc:  # noqa: BLE001 — message propre à l'UI
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.get(
    "/me/projets/{entreprise_id}/qbo-pieces/{att_id}",
    summary="Pièce jointe QuickBooks (facture) — investisseur",
)
async def my_projet_qbo_piece(
    entreprise_id: int,
    att_id: str,
    db: DBSession,
    user: CurrentUser,
    ct: Optional[str] = None,
    nom: Optional[str] = None,
) -> Response:
    await _ma_participation_ou_404(db, user.id, entreprise_id)
    contenu = await qbo_piece_data(db, entreprise_id, att_id)
    if not contenu:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Pièce introuvable dans QuickBooks (ou téléchargement "
            "échoué).",
        )
    # Le type vient de l'écran mais n'est jamais avalé tel quel : seuls
    # image/* et PDF s'affichent inline.
    media = (ct or "").lower()
    if not (media.startswith("image/") or media == "application/pdf"):
        media = "application/octet-stream"
    entetes = {}
    if nom:
        propre = "".join(
            ch for ch in nom if ch.isalnum() or ch in "._- "
        )[:120]
        entetes["Content-Disposition"] = f'inline; filename="{propre}"'
    return Response(content=contenu, media_type=media, headers=entetes)


@router.get(
    "/me/projets/{entreprise_id}/avances",
    summary="Capital encore investi par actionnaire (soldes "
    "QuickBooks) — investisseur",
)
async def my_projet_avances(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> dict:
    """Soldes LIVE des comptes d'avances d'actionnaires, appariés aux
    actionnaires de la fiche — la liste « Capital encore investi par
    actionnaire » de la carte Ma participation. Respecte
    ``show_actionnaires``."""
    part = (
        await db.execute(
            select(InvestParticipation.id).where(
                InvestParticipation.user_id == user.id,
                InvestParticipation.entreprise_id == entreprise_id,
                InvestParticipation.is_visible.is_(True),
            )
        )
    ).scalar_one_or_none()
    if part is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Projet introuvable."
        )
    profil = await get_or_default_profil(db, entreprise_id)
    if profil is not None and not profil.show_actionnaires:
        return {"statut": "masque"}
    return await avances_par_actionnaire(db, entreprise_id)


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
