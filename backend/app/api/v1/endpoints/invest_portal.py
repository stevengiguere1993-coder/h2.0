"""Portail Investisseur v2 — endpoints CÔTÉ INVESTISSEUR (lecture seule).

    GET /invest/me/portefeuille               vue d'ensemble
    GET /invest/me/projets/{entreprise_id}    fiche projet
    GET /invest/me/documents/{doc_id}/pdf     document partagé

Un investisseur voit TOUTES les compagnies où il détient des parts
selon « Parts & actionnaires » des fiches entreprise — directement ou à
travers une de nos compagnies (cascade, `app/services/invest_cascade.py`,
Steven 2026-11-07) — sauf celles que l'admin a MASQUÉES
(`InvestParticipation.masque`). La participation persistée ne sert plus
qu'à porter les flux (apports, remboursements), le statut et l'exception
« masqué ». Les assembleurs `build_portefeuille` / `build_projet` sont
partagés avec la console admin (« voir comme lui »).

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
from app.models.audit_log import AuditLog
from app.models.invest_portal import (
    InvestDocument,
    InvestFlux,
    InvestParticipation,
)
from app.models.user import User
from app.services.invest_cascade import (
    Detention,
    Graphe,
    Identite,
    charger_graphe,
    detentions_de,
)
from app.services.invest_portfolio import (
    ajuster_capital_avec_soldes_qbo,
    avances_par_actionnaire,
    budget_ligne_transactions,
    budget_optimisation_data,
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


async def identite_de_user(db: AsyncSession, user_id: int) -> Identite:
    u = await db.get(User, user_id)
    if u is None:
        return Identite(user_id=user_id)
    return Identite.de_user(u)


async def _participations_de(
    db: AsyncSession, user_id: int
) -> dict[int, InvestParticipation]:
    """Participations PERSISTÉES de ce compte : {entreprise_id: part}."""
    if not user_id:
        return {}
    return {
        p.entreprise_id: p
        for p in (
            await db.execute(
                select(InvestParticipation)
                .where(InvestParticipation.user_id == user_id)
                .order_by(InvestParticipation.id)
            )
        ).scalars()
    }


async def _flux_of(
    db: AsyncSession, participation_id: int
) -> list[InvestFlux]:
    if not participation_id:
        return []
    return list(
        (
            await db.execute(
                select(InvestFlux)
                .where(InvestFlux.participation_id == participation_id)
                .order_by(InvestFlux.date_flux, InvestFlux.id)
            )
        ).scalars()
    )


def _part_virtuelle(user_id: int, entreprise_id: int, pct: float) -> InvestParticipation:
    """Participation NON persistée (id=0, aucun flux) : la personne
    détient des parts selon la fiche entreprise mais aucune ligne
    n'existe encore (compte pas créé, ou jamais synchronisé)."""
    part = InvestParticipation(
        user_id=user_id, entreprise_id=entreprise_id, parts_pct=pct
    )
    part.id = 0
    part.statut = "actif"
    part.masque = False
    return part


async def projets_de(
    db: AsyncSession,
    ident: Identite,
    *,
    inclure_masques: bool = False,
    graphe: Optional[Graphe] = None,
) -> list[tuple[InvestParticipation, Optional[Detention], float]]:
    """Ce que cette identité voit : [(participation (réelle ou
    virtuelle), détention en cascade ou None, % effectif)].

    - compagnies où la personne détient des parts (cascade) ;
    - + participations persistées sans ligne d'actionnaire (ajout
      manuel dans la console) au % saisi ;
    - − celles que l'admin a masquées (sauf ``inclure_masques``).
    Les holdings purs (sans immeuble ni participation persistée, qui ne
    font que détenir d'autres compagnies) sont écartés par
    ``build_portefeuille`` : ``compagnies_intermediaires`` les décrit."""
    dets = await detentions_de(db, ident, graphe)
    parts = await _participations_de(db, ident.user_id or 0)
    ids = list(dets.keys()) + [e for e in parts if e not in dets]
    out: list[tuple[InvestParticipation, Optional[Detention], float]] = []
    for eid in ids:
        part = parts.get(eid)
        if part is not None and part.masque and not inclure_masques:
            continue
        det = dets.get(eid)
        pct = det.pct_total if det is not None else float(part.parts_pct)
        if part is None:
            part = _part_virtuelle(ident.user_id or 0, eid, pct)
        out.append((part, det, pct))
    return out


async def compagnies_intermediaires(
    db: AsyncSession,
    dets: dict[int, Detention],
    projets_ids: set[int],
    graphe: Graphe,
) -> list[dict]:
    """Les compagnies PAR LESQUELLES la personne détient ses projets
    (holdings) : sa part dans chacune, la valeur de la compagnie (ses
    immeubles + ses participations dans d'autres compagnies) et sa
    valeur personnelle dedans. Steven : « Vincent peut voir la valeur
    du projet dans la compagnie X et sa valeur personnelle »."""
    holdings: dict[int, float] = {}
    for det in dets.values():
        for ch in det.chemins:
            for m in ch.maillons[:-1]:
                holdings.setdefault(m.entreprise_id, 0.0)
    if not holdings:
        return []
    for hid in holdings:
        d = dets.get(hid)
        holdings[hid] = d.pct_total if d is not None else 0.0

    cache_equite: dict[int, float] = {}

    async def _equite(eid: int, deja: frozenset) -> float:
        if eid in cache_equite:
            return cache_equite[eid]
        snap = await entreprise_snapshot(db, eid)
        total = float(snap["equite"])
        for (cible, q) in graphe.detient.get(eid, []):
            if cible in deja or q <= 0:
                continue
            total += q / 100.0 * await _equite(cible, deja | {cible})
        cache_equite[eid] = round(total, 2)
        return cache_equite[eid]

    out: list[dict] = []
    for hid, mon_pct in holdings.items():
        ent = await db.get(Entreprise, hid)
        if ent is None:
            continue
        valeur = await _equite(hid, frozenset({hid}))
        detenues = [
            {
                "entreprise_id": cible,
                "name": graphe.noms.get(cible, ""),
                "pct": round(q, 3),
                "est_projet": cible in projets_ids,
            }
            for (cible, q) in graphe.detient.get(hid, [])
        ]
        out.append(
            {
                "entreprise_id": hid,
                "name": ent.name,
                "color_accent": ent.color_accent,
                "mon_pct": round(mon_pct, 3),
                "valeur": valeur,
                "ma_valeur": round(valeur * mon_pct / 100.0, 2),
                "detient": detenues,
            }
        )
    out.sort(key=lambda c: -c["ma_valeur"])
    return out


def _carte_detention(det: Optional[Detention], pct: float) -> dict:
    if det is None:
        return {
            "pct_direct": round(pct, 3),
            "pct_indirect": 0.0,
            "chemins": [],
        }
    return {
        "pct_direct": det.pct_direct,
        "pct_indirect": det.pct_indirect,
        "chemins": [c.to_dict() for c in det.chemins],
    }


async def build_portefeuille(
    db: AsyncSession,
    user_id: int,
    identite: Optional[Identite] = None,
) -> dict:
    """Portefeuille d'une identité : ``identite`` (aperçu d'un
    actionnaire sans compte) sinon celle du compte ``user_id``."""
    ident = identite or await identite_de_user(db, user_id)
    graphe = await charger_graphe(db)
    dets = await detentions_de(db, ident, graphe)
    triples = await projets_de(db, ident, graphe=graphe)

    pairs: list[tuple[InvestParticipation, list[InvestFlux], float]] = []
    projets: list[dict] = []
    tot_capital_actuel = 0.0
    tot_capital_total = 0.0
    tot_retours = 0.0
    tot_valeur_parts = 0.0
    tot_valeur_projets = 0.0
    flux_global: list[tuple[date, float]] = []

    for part, det, pct_eff in triples:
        ent = await db.get(Entreprise, part.entreprise_id)
        if ent is None or not ent.is_active:
            continue
        snap = await entreprise_snapshot(db, part.entreprise_id)
        if (
            not snap["immeubles"]
            and part.id == 0
            and graphe.detient.get(part.entreprise_id)
        ):
            continue  # holding pur : décrit dans « compagnies »
        flux = await _flux_of(db, part.id)
        pairs.append((part, flux, pct_eff))
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
                "parts_pct": round(pct_eff, 3),
                "valeur_parts": valeur_parts,
                # Valeur GLOBALE du projet (toute la compagnie).
                "valeur_totale": snap["valeur_totale"],
                "hypotheque_totale": snap["hypotheque_totale"],
                "equite": snap["equite"],
                **_carte_detention(det, pct_eff),
                "cashflow_moyen_part": cash_part,
                "statut": part.statut,
                **k,
            }
        )
        tot_capital_actuel += k["capital_actuel"]
        tot_capital_total += k["capital_investi_total"]
        tot_retours += k["capital_rembourse"] + k["distributions_recues"]
        tot_valeur_parts += valeur_parts
        tot_valeur_projets += float(snap["valeur_totale"] or 0)
        flux_global.extend(flux_signes(flux))
        if valeur_parts:
            flux_global.append((date.today(), valeur_parts))

    projets.sort(key=lambda p: (-p["valeur_parts"], p["entreprise_name"]))
    tri_global = xirr(flux_global)
    tvpi_global = (
        round((tot_retours + tot_valeur_parts) / tot_capital_total, 4)
        if tot_capital_total > 0
        else None
    )
    serie_valeur = await serie_valeur_totale(db, pairs)
    compagnies = await compagnies_intermediaires(
        db, dets, {p["entreprise_id"] for p in projets}, graphe
    )

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
        "valeur_projets": round(tot_valeur_projets, 2),
        "tri_pct": round(tri_global * 100, 1)
        if tri_global is not None
        else None,
        "tvpi": tvpi_global,
        "serie_valeur": serie_valeur,
        "projets": projets,
        "compagnies": compagnies,
    }


async def acces_projet(
    db: AsyncSession,
    user_id: int,
    entreprise_id: int,
    identite: Optional[Identite] = None,
) -> Optional[tuple[InvestParticipation, Optional[Detention], float]]:
    """La personne voit-elle ce projet ? (participation réelle ou
    virtuelle, détention, % effectif) — None sinon (masqué, aucune
    part, compagnie inactive)."""
    ident = identite or await identite_de_user(db, user_id)
    for part, det, pct in await projets_de(db, ident):
        if part.entreprise_id == entreprise_id:
            return part, det, pct
    return None


async def _acces_projet_ou_404(
    db: AsyncSession, user_id: int, entreprise_id: int
) -> tuple[InvestParticipation, Optional[Detention], float]:
    acces = await acces_projet(db, user_id, entreprise_id)
    if acces is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Projet introuvable."
        )
    return acces


async def build_projet(
    db: AsyncSession,
    user_id: int,
    entreprise_id: int,
    identite: Optional[Identite] = None,
) -> dict:
    """Fiche projet telle que la voit ``identite`` (aperçu d'un
    actionnaire sans compte) ou le compte ``user_id``."""
    ident = identite or await identite_de_user(db, user_id)
    acces = await acces_projet(db, user_id, entreprise_id, ident)
    if acces is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Projet introuvable."
        )
    part, det, pct_eff = acces
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
    show_budget = profil.show_budget if profil else True

    snap = await entreprise_snapshot(db, entreprise_id)
    directory = await partner_directory(db, entreprise_id)
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
    # compte connecté ; `via_moi_pct` = ma part dans une compagnie
    # actionnaire (ex. « Compagnie X — 50 % (dont vous : 15 %) »).
    actionnaires: list[dict] = []
    if show_actionnaires:
        graphe = await charger_graphe(db)
        mes_dets = await detentions_de(db, ident, graphe)
        from app.services.invest_cascade import feuille_est

        for pr, row in zip(directory["partners"], directory["rows"]):
            holding = pr.partner_entreprise_id
            via_moi = None
            if holding is not None and holding in mes_dets and row[
                "ownership_pct"
            ]:
                via_moi = round(
                    mes_dets[holding].pct_total
                    * float(row["ownership_pct"])
                    / 100.0,
                    3,
                )
            actionnaires.append(
                {
                    "name": row["name"],
                    "parts_pct": row["ownership_pct"],
                    "is_me": (
                        holding is None and feuille_est(graphe, pr, ident)
                    ),
                    "entreprise_id": holding,
                    "via_moi_pct": via_moi,
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
        "parts_pct": round(pct_eff, 3),
        "valeur_parts": valeur_parts,
        **_carte_detention(det, pct_eff),
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
        "show_budget": show_budget,
        # Dossier Google Drive partagé (retour investisseur 2026-09-02)
        # — alternative à l'hébergement des documents dans l'app.
        "drive_folder_url": (
            profil.drive_folder_url if profil is not None else None
        ),
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


async def _log_consultation(
    db, user, page: str, entreprise_id: int | None = None
) -> None:
    """Journalise « l'investisseur a consulté sa page » (chantier « IA
    au courant de tout », GO Phil 2026-09-02) — UNE entrée par
    utilisateur / page / entité / JOUR pour rester lisible. Best-effort
    intégral : jamais bloquant pour la page."""
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        debut_jour = (
            datetime.now(ZoneInfo("America/Toronto"))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
        action = f"invest.consultation.{page}"
        q = select(AuditLog.id).where(
            AuditLog.user_id == user.id,
            AuditLog.action == action,
            AuditLog.created_at >= debut_jour,
        )
        if entreprise_id is not None:
            q = q.where(AuditLog.entity_id == entreprise_id)
        deja = (await db.execute(q.limit(1))).scalar_one_or_none()
        if deja is not None:
            return
        from app.services.audit import log_action

        await log_action(
            db,
            user=user,
            action=action,
            entity_type="entreprise" if entreprise_id else "invest",
            entity_id=entreprise_id,
            details={"page": page},
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — le tracking ne casse jamais la page
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


@router.get(
    "/me/portefeuille",
    summary="Vue d'ensemble du portefeuille de l'investisseur connecté",
)
async def my_portefeuille(db: DBSession, user: CurrentUser) -> dict:
    out = await build_portefeuille(db, user.id)
    await _log_consultation(db, user, "portefeuille")
    return out


@router.get(
    "/me/projets/{entreprise_id}",
    summary="Fiche projet (compagnie) de l'investisseur connecté",
)
async def my_projet(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> dict:
    out = await build_projet(db, user.id, entreprise_id)
    await _log_consultation(db, user, "projet", entreprise_id)
    return out


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
    await _acces_projet_ou_404(db, user.id, entreprise_id)
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
    """Garde des routes de détail QBO : des parts dans le projet (cascade)
    requises, et les interrupteurs de publication du projet respectés (pas de
    détail des dépenses si l'admin les masque)."""
    await _acces_projet_ou_404(db, user_id, entreprise_id)
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
    await _acces_projet_ou_404(db, user.id, entreprise_id)
    profil = await get_or_default_profil(db, entreprise_id)
    if profil is not None and not profil.show_actionnaires:
        return {"statut": "masque"}
    return await avances_par_actionnaire(db, entreprise_id)


@router.get(
    "/me/projets/{entreprise_id}/budget",
    summary="Budget du projet d'optimisation (enveloppes, dépensé, "
    "reste) — investisseur",
)
async def my_projet_budget(
    entreprise_id: int, db: DBSession, user: CurrentUser
) -> dict:
    """« Où va l'argent » : les enveloppes du projet d'optimisation
    avec le dépensé réel QuickBooks. Respecte ``show_budget``."""
    await _acces_projet_ou_404(db, user.id, entreprise_id)
    profil = await get_or_default_profil(db, entreprise_id)
    if profil is not None and not profil.show_budget:
        return {"statut": "masque"}
    return await budget_optimisation_data(db, entreprise_id)


@router.get(
    "/me/projets/{entreprise_id}/qbo-lignes/{ligne_id}/transactions",
    summary="Transactions d'une enveloppe du budget — investisseur",
)
async def my_projet_budget_txns(
    entreprise_id: int, ligne_id: int, db: DBSession, user: CurrentUser
) -> list:
    await _acces_projet_ou_404(db, user.id, entreprise_id)
    profil = await get_or_default_profil(db, entreprise_id)
    if profil is not None and not profil.show_budget:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Projet introuvable."
        )
    try:
        return await budget_ligne_transactions(
            db, entreprise_id, ligne_id
        )
    except LookupError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Enveloppe introuvable."
        )
    except Exception as exc:  # noqa: BLE001 — message propre à l'UI
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


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
    portefeuille = await ajuster_capital_avec_soldes_qbo(
        db, portefeuille, user_id=user.id
    )
    pdf = await build_releve_pdf(
        db, user, year, portefeuille, ident_user_id=user.id
    )
    await _log_consultation(db, user, "releve")
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
    if await acces_projet(db, user.id, doc.entreprise_id) is None:
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
