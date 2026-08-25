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
# Annuaire « Parts & actionnaires » — SOURCE DE VÉRITÉ des parts
# ─────────────────────────────────────────────────────────────────────


async def partner_directory(
    db: AsyncSession, entreprise_id: int
) -> dict:
    """Actionnaires déclarés dans la fiche entreprise (gestion
    d'entreprise) : la seule source des noms et des % de parts.

    Retourne {"rows": [...], "by_user": {user_id: row}} où chaque row =
    {partner_id, name, ownership_pct, email, user_id}. Le `partner_name`
    saisi (souvent un holding) PRIME sur le nom du compte lié."""
    from app.models.entreprise import EntreprisePartner
    from app.models.user import User

    rows: list[dict] = []
    by_user: dict[int, dict] = {}
    for pr in (
        await db.execute(
            select(EntreprisePartner)
            .where(EntreprisePartner.entreprise_id == entreprise_id)
            .order_by(EntreprisePartner.id)
        )
    ).scalars():
        pu = None
        if pr.user_id:
            pu = await db.get(User, pr.user_id)
        if pu is None and pr.partner_email:
            pu = (
                await db.execute(
                    select(User).where(
                        func.lower(User.email)
                        == pr.partner_email.strip().lower()
                    )
                )
            ).scalar_one_or_none()
        name = (pr.partner_name or "").strip() or (
            f"{pu.first_name or ''} {pu.last_name or ''}".strip()
            or pu.email
            if pu
            else "—"
        )
        row = {
            "partner_id": pr.id,
            "name": name,
            "ownership_pct": (
                float(pr.ownership_pct)
                if pr.ownership_pct is not None
                else None
            ),
            "email": (
                (pu.email if pu else pr.partner_email) or ""
            ).strip().lower()
            or None,
            "user_id": pu.id if pu else None,
        }
        rows.append(row)
        if pu is not None and pu.id not in by_user:
            by_user[pu.id] = row
    return {"rows": rows, "by_user": by_user}


def effective_parts_pct(
    part: InvestParticipation, directory: Optional[dict]
) -> float:
    """% de parts EFFECTIF d'une participation : celui de la fiche
    entreprise (Parts & actionnaires) quand l'actionnaire y est apparié,
    sinon le % stocké sur la participation."""
    if directory:
        row = directory["by_user"].get(part.user_id)
        if row and row["ownership_pct"] is not None:
            return float(row["ownership_pct"])
    return float(part.parts_pct)


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
        loyers_potentiels = 0.0
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
            if m_aff is not None:
                loyers_potentiels += m_aff
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
                "loyers_potentiels": round(loyers_potentiels, 2),
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
                # Détail COMPLET des hypothèques actives — section
                # « Hypothèques » de la fiche projet.
                "hypotheques": [
                    {
                        "id": h.id,
                        "rang": h.rang,
                        "preteur": h.preteur,
                        "montant_initial": (
                            float(h.montant_initial)
                            if h.montant_initial is not None
                            else None
                        ),
                        "balance": round(balance_effective(h), 2),
                        "taux_pct": (
                            float(h.taux_pct)
                            if h.taux_pct is not None
                            else None
                        ),
                        "type_taux": h.type_taux,
                        "paiement_mensuel": (
                            float(h.paiement_mensuel)
                            if h.paiement_mensuel is not None
                            else None
                        ),
                        "amortissement_mois": h.amortissement_mois,
                        "date_debut": h.date_debut,
                        "date_fin_terme": h.date_fin_terme,
                    }
                    for h in sorted(hyps, key=lambda x: x.rang or 99)
                ],
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
    db: AsyncSession, entreprise_id: int, months: Optional[int] = None
) -> dict:
    """Série mensuelle revenus / dépenses (pondérée par le % de
    détention), alignée sur la FICHE IMMEUBLE du pôle locatif.

    ``months=None`` = fenêtre AUTO : depuis le premier achat d'immeuble
    (plafonnée à 72 mois, plancher 12) — le frontend filtre ensuite par
    année. Passer un entier pour une fenêtre fixe (ex. 12 pour les
    cartes du portefeuille).

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
    if months is None:
        months = 12
        achats = [
            imm.purchase_date for imm, _ in pairs if imm.purchase_date
        ]
        if achats:
            premier = _month_start(min(achats))
            auj = _month_start(date.today())
            ecart = (
                (auj.year - premier.year) * 12
                + (auj.month - premier.month)
                + 1
            )
            months = max(12, min(72, ecart))
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
        # Les récurrentes ne s'étalent pas avant l'achat de l'immeuble.
        imm_debut = (
            _month_start(imm.purchase_date)
            if imm.purchase_date
            else keys[0]
        )
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
                    if k >= imm_debut:
                        dep[k] += base * pct
            elif d.frequence == "annuel":
                dep_recurrentes += base / 12.0 * pct
                par_categorie[cat] = par_categorie.get(cat, 0.0) + base * pct
                for k in keys:
                    if k >= imm_debut:
                        dep[k] += base / 12.0 * pct
            elif d.date_depense:
                k = _month_start(d.date_depense)
                if k in dep:
                    dep[k] += base * pct
                    # Le palmarès par catégorie reste sur 12 mois même
                    # quand la série couvre plus loin.
                    if k >= _add_months(_month_start(date.today()), -11):
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
        achats = [
            imm.purchase_date for imm, _ in pairs if imm.purchase_date
        ]
        depuis = _month_start(min(achats)) if achats else keys[0]
        for k in keys:
            rev[k] = loyers_effectifs if k >= depuis else 0.0

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
    # % effectifs (fiche entreprise) — annuaire par compagnie, une fois.
    directories: dict[int, dict] = {}
    for part, _fl in participations:
        if part.entreprise_id not in directories:
            directories[part.entreprise_id] = await partner_directory(
                db, part.entreprise_id
            )
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
            pct = effective_parts_pct(
                part, directories.get(part.entreprise_id)
            ) / 100.0
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
        # Financements / refinancements : chaque hypothèque ACTIVE datée
        # devient un événement (un refi = nouvelle hypothèque au pôle
        # locatif → il apparaît ici tout seul). On saute celle qui
        # démarre le jour de l'achat (déjà couverte par l'acquisition).
        for h in await hypotheques_actives(db, imm.id):
            if h.date_debut is None:
                continue
            if imm.purchase_date and abs(
                (h.date_debut - imm.purchase_date).days
            ) <= 31:
                continue
            montant = (
                f" — {int(float(h.montant_initial)):,} $".replace(",", " ")
                if h.montant_initial
                else ""
            )
            taux = (
                f" · {float(h.taux_pct):g} %" if h.taux_pct is not None else ""
            )
            events.append(
                {
                    "date": h.date_debut.isoformat(),
                    "kind": "refinancement",
                    "titre": (
                        f"Financement — {h.preteur or 'hypothèque'}"
                        f"{montant}"
                    ),
                    "description": f"{imm.name}{taux}",
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


# ─────────────────────────────────────────────────────────────────────
# Revenus / dépenses RÉELS (QuickBooks du projet d'optimisation)
# ─────────────────────────────────────────────────────────────────────


async def optimisation_projet_qbo(
    db: AsyncSession, entreprise_id: int
) -> tuple[Optional[OptimisationProjet], Optional[OptimisationProjet]]:
    """(projet avec connexion QBO, premier projet tout court) de la
    compagnie — actifs d'abord."""
    projets = (
        await db.execute(
            select(OptimisationProjet)
            .where(OptimisationProjet.entreprise_id == entreprise_id)
            .order_by(
                (OptimisationProjet.status == "actif").desc(),
                OptimisationProjet.id.desc(),
            )
        )
    ).scalars().all()
    if not projets:
        return None, None
    avec_qbo = next((x for x in projets if x.qbo_scope), None)
    return avec_qbo, projets[0]


async def avances_par_actionnaire(
    db: AsyncSession, entreprise_id: int
) -> dict:
    """Soldes LIVE des comptes d'avances d'actionnaires — la MÊME
    lecture QuickBooks que l'encadré « Avances des actionnaires » de la
    page Optimisation — appariés aux actionnaires de la fiche
    entreprise avec les mêmes règles de nom que la sync nocturne.

    Le solde d'un compte d'avances = ce que la compagnie doit encore à
    l'actionnaire = son capital encore investi. C'est la liste que Phil
    veut voir coller à QuickBooks (retour 2026-08-25). Statuts :
    aucun_projet | sans_qbo | erreur | connecte."""
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
        log.info("invest avances entreprise #%s: %s", entreprise_id, exc)
        return {"statut": "erreur", "erreur": str(exc)[:300]}

    # Appariement compte ↔ actionnaire : mêmes jetons de nom que la
    # sync (ordre des mots indifférent, mots génériques ignorés).
    from app.models.user import User
    from app.services.invest_qbo_sync import _match, _tokens

    directory = await partner_directory(db, entreprise_id)
    lignes: list[dict] = []
    candidats: list[set] = []
    for row in directory["rows"]:
        noms = {frozenset(_tokens(row["name"]))}
        if row["user_id"]:
            u = await db.get(User, row["user_id"])
            if u:
                noms.add(
                    frozenset(
                        _tokens(f"{u.first_name or ''} {u.last_name or ''}")
                    )
                )
                if u.last_name and len(u.last_name) > 3:
                    noms.add(frozenset(_tokens(u.last_name)))
        candidats.append({n for n in noms if n})
        lignes.append({"name": row["name"], "solde": None, "comptes": []})

    autres: list[dict] = []
    for compte in av.get("comptes") or []:
        toks = _tokens(str(compte.get("nom") or ""))
        solde = float(compte.get("solde") or 0)
        matches = [
            i for i, noms in enumerate(candidats) if _match(noms, toks)
        ]
        if len(matches) == 1:
            ligne = lignes[matches[0]]
            ligne["solde"] = round((ligne["solde"] or 0.0) + solde, 2)
            ligne["comptes"].append(str(compte.get("nom") or ""))
        elif abs(solde) >= 0.005:
            # Compte actif qu'on ne sait pas rattacher : montré quand
            # même — rien ne doit disparaître de la liste.
            autres.append(
                {
                    "nom": str(compte.get("nom") or "?"),
                    "solde": round(solde, 2),
                }
            )
    return {
        "statut": "connecte",
        "projet_nom": p.name,
        "actionnaires": lignes,
        "autres_comptes": autres,
        "total": av.get("total"),
    }


async def budget_optimisation_data(
    db: AsyncSession, entreprise_id: int
) -> dict:
    """Le tableau Budget du projet d'optimisation, résumé pour le
    portail investisseur (retour Phil 2026-08-25 : « je veux que mes
    investisseurs puissent voir où est-ce que leur argent a été
    dépensé ») : par enveloppe → budget, dépensé réel QuickBooks,
    reste. MÊME calcul que la page Optimisation : somme des comptes
    mappés (P&L + immobilisations du bilan) ; l'enveloppe « détention »
    (deficit_operation) = déficit d'opération du cashflow. Statuts :
    aucun_projet | sans_qbo | erreur | connecte."""
    p, premier = await optimisation_projet_qbo(db, entreprise_id)
    if premier is None:
        return {"statut": "aucun_projet"}
    if p is None:
        return {"statut": "sans_qbo", "projet_nom": premier.name}

    import json as _json

    from app.models.optimisation import OptimisationBudgetLigne
    from app.services.qbo_optimisation import (
        cashflow_mensuel,
        depenses_par_compte,
    )

    lignes = (
        await db.execute(
            select(OptimisationBudgetLigne)
            .where(OptimisationBudgetLigne.projet_id == p.id)
            .order_by(OptimisationBudgetLigne.id)
        )
    ).scalars().all()
    debut = (p.date_debut or date(2000, 1, 1)).isoformat()
    try:
        totaux = await depenses_par_compte(
            p.qbo_scope, debut, date.today().isoformat()
        )
    except Exception as exc:  # noqa: BLE001 — message propre à l'UI
        log.info("invest budget entreprise #%s: %s", entreprise_id, exc)
        return {"statut": "erreur", "erreur": str(exc)[:300]}

    def _somme(raw) -> float:
        try:
            comptes = _json.loads(raw or "[]")
        except Exception:  # noqa: BLE001 — mapping illisible = 0
            return 0.0
        return sum(
            float(totaux.get(str(c.get("id")), 0.0)) for c in comptes
        )

    ecart_total = None
    if any(l.mode == "deficit_operation" for l in lignes):
        try:
            cf = await cashflow_mensuel(
                p.qbo_scope,
                debut,
                date.today().isoformat(),
                hypotheque_account_id=p.qbo_hypotheque_account_id,
            )
            ecart_total = float((cf or {}).get("total", {}).get("ecart", 0))
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            log.info(
                "invest budget cashflow #%s: %s", entreprise_id, exc
            )

    rows: list[dict] = []
    total_budget = total_depense = 0.0
    for l in lignes:
        if l.mode == "deficit_operation":
            dep = (
                round(-ecart_total, 2)
                if ecart_total is not None
                else None
            )
        else:
            dep = round(_somme(l.qbo_accounts_json), 2)
        budget = float(l.budget_montant or 0)
        rows.append(
            {
                "ligne_id": l.id,
                "nom": l.nom,
                "mode": l.mode,
                "budget": round(budget, 2),
                "depense": dep,
                "reste": (
                    round(budget - dep, 2) if dep is not None else None
                ),
            }
        )
        total_budget += budget
        total_depense += dep or 0.0
    return {
        "statut": "connecte",
        "projet_nom": p.name,
        "date_debut": p.date_debut.isoformat() if p.date_debut else None,
        "lignes": rows,
        "total": {
            "budget": round(total_budget, 2),
            "depense": round(total_depense, 2),
            "reste": round(total_budget - total_depense, 2),
        },
    }


async def budget_ligne_transactions(
    db: AsyncSession, entreprise_id: int, ligne_id: int
) -> list:
    """Transactions QuickBooks derrière le « dépensé » d'une enveloppe
    du budget, factures jointes comprises. LookupError si l'enveloppe
    n'appartient pas au projet de la compagnie ; RuntimeError sans
    connexion QuickBooks."""
    p, _ = await optimisation_projet_qbo(db, entreprise_id)
    if p is None:
        raise RuntimeError(
            "Aucune connexion QuickBooks pour cette compagnie."
        )
    import json as _json

    from app.models.optimisation import OptimisationBudgetLigne

    ligne = (
        await db.execute(
            select(OptimisationBudgetLigne).where(
                OptimisationBudgetLigne.id == ligne_id,
                OptimisationBudgetLigne.projet_id == p.id,
            )
        )
    ).scalar_one_or_none()
    if ligne is None:
        raise LookupError("Enveloppe introuvable.")
    try:
        comptes = {
            str(c.get("id"))
            for c in _json.loads(ligne.qbo_accounts_json or "[]")
            if c.get("id") is not None
        }
    except Exception:  # noqa: BLE001
        comptes = set()
    if not comptes:
        return []
    from app.services.qbo_optimisation import transactions_depenses

    return await transactions_depenses(
        p.qbo_scope,
        comptes,
        (p.date_debut or date(2000, 1, 1)).isoformat(),
        date.today().isoformat(),
    )


async def qbo_txns_compte_data(
    db: AsyncSession,
    entreprise_id: int,
    compte_id: str,
    debut: str,
    fin: str,
) -> list:
    """Transactions QuickBooks d'UN compte de dépense sur une période,
    via le projet d'optimisation de la compagnie — le clic sur un compte
    du tableau « Revenus et dépenses réels » mène ici (même principe que
    la page Optimisation, demande Phil 2026-08-25). Lève RuntimeError si
    la compagnie n'a pas de connexion QuickBooks."""
    p, _ = await optimisation_projet_qbo(db, entreprise_id)
    if p is None:
        raise RuntimeError(
            "Aucune connexion QuickBooks pour cette compagnie."
        )
    from app.services.qbo_optimisation import transactions_depenses

    return await transactions_depenses(p.qbo_scope, {compte_id}, debut, fin)


async def qbo_piece_data(
    db: AsyncSession, entreprise_id: int, att_id: str
) -> Optional[bytes]:
    """Pièce jointe QuickBooks (facture PDF/image) servie EN DIRECT —
    rien n'est stocké. Le scope vient du projet d'optimisation de la
    compagnie : impossible de viser la connexion d'un autre pôle."""
    p, _ = await optimisation_projet_qbo(db, entreprise_id)
    if p is None:
        return None
    from app.integrations.quickbooks import get_qbo

    return await get_qbo(p.qbo_scope).download_attachable(att_id)


async def qbo_reels_data(db: AsyncSession, entreprise_id: int) -> dict:
    """Série mensuelle RÉELLE (QuickBooks) de la compagnie, via son
    projet de la section optimisation — depuis l'ouverture du projet
    (ou le premier achat d'immeuble). Statuts :

    - aucun_projet : rien dans la section optimisation → « non
      applicable / pas encore rentré » côté UI ;
    - sans_qbo     : projet présent mais aucune connexion QuickBooks ;
    - erreur       : lecture QBO impossible (token, réseau…) ;
    - connecte     : rows {mois, revenus, depenses, hypotheque, ecart,
      details} + total de période."""
    p, premier = await optimisation_projet_qbo(db, entreprise_id)
    if premier is None:
        return {"statut": "aucun_projet"}
    if p is None:
        return {"statut": "sans_qbo", "projet_nom": premier.name}
    debut = p.date_debut
    if debut is None:
        achats = [
            imm.purchase_date
            for imm, _ in await immeubles_of_entreprise(db, entreprise_id)
            if imm.purchase_date
        ]
        debut = min(achats) if achats else date(2000, 1, 1)
    try:
        from app.services.qbo_optimisation import cashflow_mensuel

        cf = await cashflow_mensuel(
            p.qbo_scope,
            debut.isoformat(),
            date.today().isoformat(),
            hypotheque_account_id=p.qbo_hypotheque_account_id,
        )
    except Exception as exc:  # noqa: BLE001 — message propre à l'UI
        log.info("invest qbo-reels entreprise #%s: %s", entreprise_id, exc)
        return {
            "statut": "erreur",
            "projet_nom": p.name,
            "erreur": str(exc)[:300],
        }
    return {
        "statut": "connecte",
        "projet_nom": p.name,
        "rows": (cf or {}).get("mois", []),
        "total": (cf or {}).get("total"),
    }
