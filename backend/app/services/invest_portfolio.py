"""Portail Investisseur v2 — assemblage des données par compagnie.

Tout part de la chaîne existante :

    Entreprise ← Immeuble.owner_entreprise_id
    Entreprise ← ImmeubleOwnership (% de détention par immeuble)

et des données du pôle locatif : baux (loyers), paiements, dépenses,
hypothèques (balance effective via `hypotheque_calc`), évaluations
(cascade : référence → plus récente → municipale → prix d'achat).

Aucune écriture ici — service de LECTURE consommé par les endpoints
admin (`invest_admin`) et investisseur (`invest_portal`).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entreprise import Entreprise
from app.models.immobilier import (
    Bail,
    BailStatus,
    DepenseImmeuble,
    Evaluation,
    EvaluationKind,
    Hypotheque,
    HypothequeStatus,
    Immeuble,
    ImmeubleOwnership,
    Logement,
    PaiementLoyer,
)
from app.models.invest_portal import (
    InvestFlux,
    InvestFluxType,
    InvestJalon,
    InvestParticipation,
    InvestProjetProfil,
)
from app.models.optimisation import OptimisationProjet
from app.services.hypotheque_calc import balance_calculee_de, balance_effective
from app.services.invest_tri import xirr

log = logging.getLogger(__name__)

_MONTHS_FR = (
    "janv.", "févr.", "mars", "avr.", "mai", "juin",
    "juil.", "août", "sept.", "oct.", "nov.", "déc.",
)


def month_label(d: date) -> str:
    return f"{_MONTHS_FR[d.month - 1]} {d.year}"


# ─────────────────────────────────────────────────────────────────────
# Immeubles d'une compagnie (avec % de détention)
# ─────────────────────────────────────────────────────────────────────


async def immeubles_of_entreprise(
    db: AsyncSession, entreprise_id: int
) -> list[tuple[Immeuble, float]]:
    """[(immeuble, pct_détention 0-100)] — union de `ImmeubleOwnership`
    et du raccourci `owner_entreprise_id` (100 % si aucune ligne)."""
    out: dict[int, tuple[Immeuble, float]] = {}
    rows = (
        await db.execute(
            select(ImmeubleOwnership, Immeuble)
            .join(Immeuble, Immeuble.id == ImmeubleOwnership.immeuble_id)
            .where(
                ImmeubleOwnership.entreprise_id == entreprise_id,
                Immeuble.is_active.is_(True),
            )
        )
    ).all()
    for own, imm in rows:
        out[imm.id] = (imm, float(own.ownership_pct or 100))
    direct = (
        await db.execute(
            select(Immeuble).where(
                Immeuble.owner_entreprise_id == entreprise_id,
                Immeuble.is_active.is_(True),
            )
        )
    ).scalars().all()
    for imm in direct:
        out.setdefault(imm.id, (imm, 100.0))
    return list(out.values())


# ─────────────────────────────────────────────────────────────────────
# Valorisation d'un immeuble (cascade d'évaluations)
# ─────────────────────────────────────────────────────────────────────


async def valeur_immeuble(
    db: AsyncSession, imm: Immeuble
) -> tuple[Optional[float], Optional[str], Optional[date]]:
    """(valeur, source, date) — référence → plus récente → municipale →
    prix d'achat. Même cascade que le portefeuille v0/la fiche."""
    row = (
        await db.execute(
            select(Evaluation.valeur, Evaluation.date_evaluation)
            .where(
                and_(
                    Evaluation.immeuble_id == imm.id,
                    Evaluation.is_reference.is_(True),
                )
            )
            .order_by(Evaluation.date_evaluation.desc())
            .limit(1)
        )
    ).first()
    if row and row[0] is not None:
        return float(row[0]), "reference", row[1]
    row = (
        await db.execute(
            select(Evaluation.valeur, Evaluation.date_evaluation)
            .where(Evaluation.immeuble_id == imm.id)
            .order_by(Evaluation.date_evaluation.desc())
            .limit(1)
        )
    ).first()
    if row and row[0] is not None:
        return float(row[0]), "evaluation", row[1]
    row = (
        await db.execute(
            select(Evaluation.valeur, Evaluation.date_evaluation)
            .where(
                and_(
                    Evaluation.immeuble_id == imm.id,
                    Evaluation.kind == EvaluationKind.MUNICIPALE.value,
                )
            )
            .order_by(Evaluation.date_evaluation.desc())
            .limit(1)
        )
    ).first()
    if row and row[0] is not None:
        return float(row[0]), "municipale", row[1]
    if imm.purchase_price:
        return float(imm.purchase_price), "achat", imm.purchase_date
    return None, None, None


async def hypotheques_actives(
    db: AsyncSession, immeuble_id: int
) -> list[Hypotheque]:
    return list(
        (
            await db.execute(
                select(Hypotheque).where(
                    Hypotheque.immeuble_id == immeuble_id,
                    Hypotheque.status == HypothequeStatus.ACTIVE.value,
                )
            )
        ).scalars()
    )


# ─────────────────────────────────────────────────────────────────────
# Snapshot financier d'une compagnie
# ─────────────────────────────────────────────────────────────────────


async def entreprise_snapshot(db: AsyncSession, entreprise_id: int) -> dict:
    """Chiffres agrégés de la compagnie : par immeuble (valeur,
    hypothèque, équité, loyers, occupation) + totaux pondérés par le %
    de détention."""
    pairs = await immeubles_of_entreprise(db, entreprise_id)
    immeubles: list[dict] = []
    tot_valeur = tot_hypo = tot_equite = 0.0
    tot_loyers = 0.0
    tot_logements = tot_baux = 0
    paiement_hypo_mensuel = 0.0

    from app.models.immobilier import LogementStatus
    from app.services.loyer_effectif import loyer_effectif_loue

    for imm, own_pct in pairs:
        pct = own_pct / 100.0
        val, val_source, val_date = await valeur_immeuble(db, imm)
        hyps = await hypotheques_actives(db, imm.id)
        balance = round(sum(balance_effective(h) for h in hyps), 2)
        pay_mensuel = sum(float(h.paiement_mensuel or 0) for h in hyps)
        # Hypothèque de 1er rang pour l'affichage (prêteur, taux, terme).
        hyp1 = min(hyps, key=lambda h: h.rang or 99) if hyps else None

        # Revenu mensuel = loyer EFFECTIF des unités louées — même
        # hiérarchie que la fiche immeuble (bail actif en interne,
        # loyer saisi en gestion externe, cf. loyer_effectif.py).
        logements = (
            await db.execute(
                select(Logement).where(Logement.immeuble_id == imm.id)
            )
        ).scalars().all()
        log_ids = [lg.id for lg in logements]
        loyer_bail_par_log: dict[int, float] = {}
        if log_ids:
            for b in (
                await db.execute(
                    select(Bail).where(
                        Bail.logement_id.in_(log_ids),
                        Bail.status == BailStatus.ACTIF.value,
                    )
                )
            ).scalars().all():
                loyer_bail_par_log[b.logement_id] = (
                    loyer_bail_par_log.get(b.logement_id, 0.0)
                    + float(b.loyer_mensuel or 0)
                )
        from app.services.loyer_effectif import loyer_effectif

        externe = bool(getattr(imm, "gestion_externe", False))
        loyers_mensuels = 0.0
        nb_loues = 0
        nb_actifs = 0
        logements_rows: list[dict] = []
        for lg in logements:
            if lg.status == LogementStatus.HORS_LOC.value:
                continue
            nb_actifs += 1
            m_loue = loyer_effectif_loue(
                lg, loyer_bail_par_log.get(lg.id), externe
            )
            m_aff = loyer_effectif(
                lg, loyer_bail_par_log.get(lg.id), externe
            )
            if m_loue is not None:
                loyers_mensuels += m_loue
                nb_loues += 1
            logements_rows.append(
                {
                    "logement_id": lg.id,
                    "numero": getattr(lg, "numero", None),
                    "loue": m_loue is not None,
                    "loyer": round(m_aff, 2) if m_aff is not None else None,
                }
            )
        logements_rows.sort(key=lambda r: str(r["numero"] or ""))
        nb_log = nb_actifs
        nb_baux = nb_loues

        equite = (val or 0.0) - balance
        immeubles.append(
            {
                "immeuble_id": imm.id,
                "name": imm.name,
                "address": imm.address,
                "cover_photo_url": imm.cover_photo_url,
                "nb_logements": nb_log,
                "nb_baux_actifs": nb_baux,
                "loyers_mensuels": round(loyers_mensuels, 2),
                "valeur": val,
                "valeur_source": val_source,
                "valeur_date": val_date,
                "hypotheque_balance": balance,
                "hypotheque_preteur": hyp1.preteur if hyp1 else None,
                "hypotheque_taux_pct": (
                    float(hyp1.taux_pct)
                    if hyp1 and hyp1.taux_pct is not None
                    else None
                ),
                "hypotheque_fin_terme": (
                    hyp1.date_fin_terme if hyp1 else None
                ),
                "equite": round(equite, 2),
                "ownership_pct": own_pct,
                "purchase_price": (
                    float(imm.purchase_price) if imm.purchase_price else None
                ),
                "purchase_date": imm.purchase_date,
                "logements": logements_rows,
            }
        )
        tot_valeur += (val or 0.0) * pct
        tot_hypo += balance * pct
        tot_equite += equite * pct
        tot_loyers += loyers_mensuels * pct
        tot_logements += nb_log
        tot_baux += nb_baux
        paiement_hypo_mensuel += pay_mensuel * pct

    # Avances aux actionnaires (dette envers eux) — soustraites de
    # l'équité de la compagnie : équité = valeur − hypothèques − avances.
    profil = await get_or_default_profil(db, entreprise_id)
    avances = (
        float(profil.avances_actionnaires)
        if profil is not None and profil.avances_actionnaires is not None
        else 0.0
    )

    return {
        "immeubles": immeubles,
        "valeur_totale": round(tot_valeur, 2),
        "hypotheque_totale": round(tot_hypo, 2),
        "avances_actionnaires": round(avances, 2),
        "equite": round(tot_equite - avances, 2),
        "loyers_mensuels": round(tot_loyers, 2),
        "nb_logements": tot_logements,
        "nb_baux_actifs": tot_baux,
        "taux_occupation": (
            round(tot_baux / tot_logements * 100, 1)
            if tot_logements
            else None
        ),
        "paiement_hypo_mensuel": round(paiement_hypo_mensuel, 2),
    }


# ─────────────────────────────────────────────────────────────────────
# Série mensuelle revenus / dépenses (12 derniers mois)
# ─────────────────────────────────────────────────────────────────────


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, n: int) -> date:
    y, m = divmod((d.year * 12 + d.month - 1) + n, 12)
    return date(y, m + 1, 1)


async def serie_mensuelle(
    db: AsyncSession, entreprise_id: int, months: int = 12
) -> dict:
    """Série mensuelle revenus / dépenses (pondérée par le % de
    détention), alignée sur la FICHE IMMEUBLE du pôle locatif :

    - revenus : paiements ENREGISTRÉS (internes + gestion externe) s'il
      y en a ; sinon repli sur le loyer EFFECTIF des unités louées
      (`loyer_effectif_loue`) — un immeuble sans suivi des paiements
      n'affiche plus 0 (mode « potentiel ») ;
    - dépenses : récurrentes mensualisées (mensuel ×1, annuel /12,
      % des loyers converti, taxable ×1.14975) + ponctuelles à leur
      date ;
    - cashflow_moyen : loyers effectifs − dépenses récurrentes −
      hypothèque (MÊME convention que `cash_flow_mensuel` de la fiche).
    """
    from app.models.immobilier import PaiementExterne
    from app.services.loyer_effectif import loyer_effectif_loue

    pairs = await immeubles_of_entreprise(db, entreprise_id)
    start = _add_months(_month_start(date.today()), -(months - 1))
    keys = [_add_months(start, i) for i in range(months)]
    rev: dict[date, float] = {k: 0.0 for k in keys}
    dep: dict[date, float] = {k: 0.0 for k in keys}
    hypo_mensuel = 0.0
    loyers_effectifs = 0.0
    dep_recurrentes = 0.0
    par_categorie: dict[str, float] = {}

    for imm, own_pct in pairs:
        pct = own_pct / 100.0
        logements = (
            await db.execute(
                select(Logement).where(Logement.immeuble_id == imm.id)
            )
        ).scalars().all()
        log_ids = [lg.id for lg in logements]

        # Paiements ENREGISTRÉS : loyers internes (par bail) + gestion
        # externe (par logement).
        if log_ids:
            bail_ids = (
                await db.execute(
                    select(Bail.id).where(Bail.logement_id.in_(log_ids))
                )
            ).scalars().all()
            if bail_ids:
                rows = (
                    await db.execute(
                        select(
                            PaiementLoyer.mois_couvert,
                            func.sum(PaiementLoyer.montant),
                        )
                        .where(
                            PaiementLoyer.bail_id.in_(list(bail_ids)),
                            PaiementLoyer.mois_couvert >= start,
                        )
                        .group_by(PaiementLoyer.mois_couvert)
                    )
                ).all()
                for mois, total in rows:
                    k = _month_start(mois)
                    if k in rev:
                        rev[k] += float(total or 0) * pct
            rows = (
                await db.execute(
                    select(
                        PaiementExterne.mois_couvert,
                        func.sum(PaiementExterne.montant),
                    )
                    .where(
                        PaiementExterne.logement_id.in_(log_ids),
                        PaiementExterne.mois_couvert >= start,
                    )
                    .group_by(PaiementExterne.mois_couvert)
                )
            ).all()
            for mois, total in rows:
                k = _month_start(mois)
                if k in rev:
                    rev[k] += float(total or 0) * pct

        # Loyer effectif des unités louées — même hiérarchie que la
        # fiche (bail actif / loyer saisi en externe).
        loyer_bail_par_log: dict[int, float] = {}
        if log_ids:
            for b in (
                await db.execute(
                    select(Bail).where(
                        Bail.logement_id.in_(log_ids),
                        Bail.status == BailStatus.ACTIF.value,
                    )
                )
            ).scalars().all():
                loyer_bail_par_log[b.logement_id] = (
                    loyer_bail_par_log.get(b.logement_id, 0.0)
                    + float(b.loyer_mensuel or 0)
                )
        externe = bool(getattr(imm, "gestion_externe", False))
        loyers_imm = 0.0
        for lg in logements:
            m = loyer_effectif_loue(
                lg, loyer_bail_par_log.get(lg.id), externe
            )
            if m is not None:
                loyers_imm += m
        loyers_effectifs += loyers_imm * pct

        depenses = (
            await db.execute(
                select(DepenseImmeuble).where(
                    DepenseImmeuble.immeuble_id == imm.id
                )
            )
        ).scalars().all()
        for d in depenses:
            base = float(d.montant or 0)
            if d.is_pourcentage:
                base = loyers_imm * base / 100.0
            if d.taxable:
                base *= 1.14975
            cat = (getattr(d, "categorie", None) or "autre").strip()
            if d.frequence == "mensuel":
                dep_recurrentes += base * pct
                par_categorie[cat] = (
                    par_categorie.get(cat, 0.0) + base * 12 * pct
                )
                for k in keys:
                    dep[k] += base * pct
            elif d.frequence == "annuel":
                dep_recurrentes += base / 12.0 * pct
                par_categorie[cat] = par_categorie.get(cat, 0.0) + base * pct
                for k in keys:
                    dep[k] += base / 12.0 * pct
            elif d.date_depense:
                k = _month_start(d.date_depense)
                if k in dep:
                    dep[k] += base * pct
                    par_categorie[cat] = (
                        par_categorie.get(cat, 0.0) + base * pct
                    )

        hyps = await hypotheques_actives(db, imm.id)
        hypo_mensuel += sum(
            float(h.paiement_mensuel or 0) for h in hyps
        ) * pct

    # Mode : « recus » si au moins un paiement est enregistré sur la
    # fenêtre, sinon « potentiel » (le graphique montre les loyers
    # effectifs — cohérent avec le pôle locatif qui affiche les loyers
    # même sans suivi détaillé des paiements).
    revenus_mode = "recus" if any(v > 0 for v in rev.values()) else "potentiel"
    if revenus_mode == "potentiel":
        for k in keys:
            rev[k] = loyers_effectifs

    rows = [
        {
            "mois": k.strftime("%Y-%m"),
            "label": month_label(k),
            "revenus": round(rev[k], 2),
            "depenses": round(dep[k], 2),
        }
        for k in keys
    ]
    # Convention de la fiche immeuble : loyers effectifs − dépenses
    # récurrentes mensualisées − hypothèque (les ponctuels n'entrent
    # pas dans le flux récurrent).
    cashflow_moyen = loyers_effectifs - dep_recurrentes - hypo_mensuel
    return {
        "rows": rows,
        "revenus_mode": revenus_mode,
        "loyers_effectifs": round(loyers_effectifs, 2),
        "hypotheque_mensuelle": round(hypo_mensuel, 2),
        "cashflow_moyen": round(cashflow_moyen, 2),
        # Total 12 mois par catégorie de dépense, trié décroissant.
        "depenses_par_categorie": sorted(
            (
                {"categorie": c, "total": round(t, 2)}
                for c, t in par_categorie.items()
            ),
            key=lambda x: -x["total"],
        ),
    }


# ─────────────────────────────────────────────────────────────────────
# Phase du projet
# ─────────────────────────────────────────────────────────────────────


async def phase_projet(
    db: AsyncSession,
    entreprise_id: int,
    profil: Optional[InvestProjetProfil],
) -> str:
    if profil is not None and profil.phase_override:
        return profil.phase_override
    actif = (
        await db.execute(
            select(OptimisationProjet.id)
            .where(
                OptimisationProjet.entreprise_id == entreprise_id,
                OptimisationProjet.status == "actif",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return "optimisation" if actif is not None else "long_terme"


# ─────────────────────────────────────────────────────────────────────
# TRI / KPIs d'une participation
# ─────────────────────────────────────────────────────────────────────


def flux_signes(flux: list[InvestFlux]) -> list[tuple[date, float]]:
    """Flux au point de vue investisseur (apport négatif)."""
    out: list[tuple[date, float]] = []
    for f in flux:
        m = float(f.montant or 0)
        if f.type == InvestFluxType.APPORT.value:
            out.append((f.date_flux, -m))
        else:
            out.append((f.date_flux, m))
    return out


def kpis_participation(
    flux: list[InvestFlux], valeur_parts: Optional[float]
) -> dict:
    apports = sum(
        float(f.montant or 0)
        for f in flux
        if f.type == InvestFluxType.APPORT.value
    )
    retours = sum(
        float(f.montant or 0)
        for f in flux
        if f.type != InvestFluxType.APPORT.value
    )
    capital_actuel = max(0.0, apports - sum(
        float(f.montant or 0)
        for f in flux
        if f.type
        in (InvestFluxType.REMBOURSEMENT.value, InvestFluxType.SORTIE.value)
    ))
    cash = flux_signes(flux)
    if valeur_parts:
        cash.append((date.today(), valeur_parts))
    tri = xirr(cash)
    tvpi = (
        round((retours + (valeur_parts or 0.0)) / apports, 4)
        if apports > 0
        else None
    )
    return {
        "capital_investi_total": round(apports, 2),
        "capital_rembourse": round(
            sum(
                float(f.montant or 0)
                for f in flux
                if f.type
                in (
                    InvestFluxType.REMBOURSEMENT.value,
                    InvestFluxType.SORTIE.value,
                )
            ),
            2,
        ),
        "distributions_recues": round(
            sum(
                float(f.montant or 0)
                for f in flux
                if f.type == InvestFluxType.DIVIDENDE.value
            ),
            2,
        ),
        "capital_actuel": round(capital_actuel, 2),
        "tri_pct": round(tri * 100, 1) if tri is not None else None,
        "tvpi": tvpi,
    }


# ─────────────────────────────────────────────────────────────────────
# Série « valeur totale créée » (graphique du portefeuille)
# ─────────────────────────────────────────────────────────────────────


async def _equite_at(
    db: AsyncSession, entreprise_id: int, at: date
) -> float:
    """Équité approximative de la compagnie à une date passée :
    évaluation la plus récente ≤ date (sinon prix d'achat si acquis),
    moins la balance CALCULÉE des hypothèques actives débutées ≤ date.
    Approximation assumée (l'historique des hypothèques remplacées
    n'est pas conservé) — le POINT FINAL de la série utilise toujours
    la valeur exacte d'aujourd'hui."""
    pairs = await immeubles_of_entreprise(db, entreprise_id)
    total = 0.0
    for imm, own_pct in pairs:
        pct = own_pct / 100.0
        if imm.purchase_date and imm.purchase_date > at:
            continue
        row = (
            await db.execute(
                select(Evaluation.valeur)
                .where(
                    Evaluation.immeuble_id == imm.id,
                    Evaluation.date_evaluation <= at,
                )
                .order_by(
                    Evaluation.is_reference.desc(),
                    Evaluation.date_evaluation.desc(),
                )
                .limit(1)
            )
        ).scalar()
        val = (
            float(row)
            if row is not None
            else (float(imm.purchase_price) if imm.purchase_price else 0.0)
        )
        balance = 0.0
        for h in await hypotheques_actives(db, imm.id):
            if h.date_debut and h.date_debut > at:
                continue
            calc = balance_calculee_de(h, aujourd_hui=at)
            balance += (
                calc if calc is not None else float(h.montant_initial or 0)
            )
        total += (val - balance) * pct
    return total


async def serie_valeur_totale(
    db: AsyncSession,
    participations: list[tuple[InvestParticipation, list[InvestFlux]]],
) -> list[dict]:
    """Points trimestriels : valeur des parts (approx. historique) +
    retours cumulés — la « valeur totale créée » du portefeuille."""
    all_flux = [f for _, fl in participations for f in fl]
    if not all_flux:
        return []
    first = min(f.date_flux for f in all_flux)
    today = date.today()
    # Points trimestriels du premier flux à aujourd'hui (max ~40 pts).
    points: list[date] = []
    cur = _month_start(first)
    while cur < today:
        points.append(cur)
        cur = _add_months(cur, 3)
    points.append(today)

    out: list[dict] = []
    for at in points:
        total = 0.0
        for part, fl in participations:
            pct = float(part.parts_pct) / 100.0
            started = any(
                f.date_flux <= at
                for f in fl
                if f.type == InvestFluxType.APPORT.value
            )
            if not started:
                continue
            equite = await _equite_at(db, part.entreprise_id, at)
            total += equite * pct
            total += sum(
                float(f.montant or 0)
                for f in fl
                if f.type != InvestFluxType.APPORT.value
                and f.date_flux <= at
            )
        out.append(
            {
                "date": at.isoformat(),
                "label": month_label(at),
                "valeur": round(total, 2),
            }
        )
    return out


# ─────────────────────────────────────────────────────────────────────
# Timeline d'un projet
# ─────────────────────────────────────────────────────────────────────


async def timeline_projet(
    db: AsyncSession,
    entreprise_id: int,
    flux: list[InvestFlux],
    phase: str,
) -> list[dict]:
    """Événements datés : acquisitions (immeubles), jalons manuels,
    remboursements/dividendes, phase courante."""
    events: list[dict] = []
    for imm, _pct in await immeubles_of_entreprise(db, entreprise_id):
        if imm.purchase_date:
            prix = (
                f" — {int(float(imm.purchase_price)):,} $".replace(",", " ")
                if imm.purchase_price
                else ""
            )
            events.append(
                {
                    "date": imm.purchase_date.isoformat(),
                    "kind": "acquisition",
                    "titre": f"Acquisition — {imm.name}{prix}",
                    "description": imm.address,
                }
            )
    jalons = (
        await db.execute(
            select(InvestJalon)
            .where(InvestJalon.entreprise_id == entreprise_id)
            .order_by(InvestJalon.date_jalon)
        )
    ).scalars().all()
    for j in jalons:
        events.append(
            {
                "date": j.date_jalon.isoformat(),
                "kind": j.kind,
                "titre": j.titre,
                "description": j.description,
            }
        )
    labels = {
        InvestFluxType.REMBOURSEMENT.value: "Remboursement de capital",
        InvestFluxType.DIVIDENDE.value: "Distribution",
        InvestFluxType.SORTIE.value: "Sortie",
    }
    for f in flux:
        if f.type == InvestFluxType.APPORT.value:
            continue
        m = f"{int(float(f.montant or 0)):,} $".replace(",", " ")
        events.append(
            {
                "date": f.date_flux.isoformat(),
                "kind": "refinancement",
                "titre": f"{labels.get(f.type, f.type)} — {m}",
                "description": f.note,
            }
        )
    events.sort(key=lambda e: e["date"])
    events.append(
        {
            "date": date.today().isoformat(),
            "kind": "phase",
            "titre": (
                "Phase d'optimisation en cours"
                if phase == "optimisation"
                else "Détention long terme"
            ),
            "description": None,
        }
    )
    return events


async def get_or_default_profil(
    db: AsyncSession, entreprise_id: int
) -> Optional[InvestProjetProfil]:
    return (
        await db.execute(
            select(InvestProjetProfil).where(
                InvestProjetProfil.entreprise_id == entreprise_id
            )
        )
    ).scalar_one_or_none()
