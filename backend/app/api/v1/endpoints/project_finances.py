"""Financial breakdown for a Project: projected (from soumission items
+ agenda-planned labour) vs actual (from achats + approved punches).

    GET /api/v1/projects/{project_id}/finances
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select

log = logging.getLogger(__name__)

from app.api.deps import CurrentUser, DBSession
from app.core.taxes import TPS_RATE, TVQ_RATE, TAX_FACTOR, ht_from_ttc
from app.models.achat import Achat
from app.models.employe import Employe
from app.models.facture import Facture, FactureStatus
from app.models.payment import Payment
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_phase import ProjectPhase
from app.models.punch import Punch
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem
from app.models.user import User
from app.core.finance_math import taxes_to_remit


router = APIRouter(prefix="/projects", tags=["project-finances"])


class CostLine(BaseModel):
    label: str
    quantity: float
    unit_cost: float
    total: float


class InvoiceLine(BaseModel):
    """Une facture du projet — sert à afficher la liste des factures
    réellement émises avec leur statut (draft/sent/paid/overdue/void),
    leur référence, leurs dates clés et le montant total."""

    id: int
    reference: str
    status: str
    total: float
    issued_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    paid_amount: float


class FinancesResponse(BaseModel):
    projected_revenue: float
    # Revenu projeté HORS TAXES (TPS/TVQ exclues) — c'est cette valeur
    # qui sert au calcul du profit. Les taxes ne sont jamais un revenu :
    # elles passent au gouvernement (« perçues pour le compte de »).
    projected_revenue_ex_tax: float = 0.0
    projected_service_cost: float
    projected_labour_cost: float
    projected_labour_hours: float
    projected_total_cost: float
    projected_profit: float
    projected_margin_pct: float

    actual_material_cost: float
    # Matériel HORS TAXES (taxes récupérables retirées) — sert au profit.
    actual_material_cost_ht: float = 0.0
    actual_labour_cost: float
    actual_labour_hours: float
    actual_total_cost: float
    # Coût réel HORS TAXES — sert au calcul du profit et à l'avancement
    # du contrat (comparé au revenu HT). La carte « Coût actuel » affiche
    # `actual_total_cost` (TTC).
    actual_total_cost_ht: float = 0.0
    actual_profit: float
    actual_margin_pct: float
    # Type de facturation de la soumission liée : "forfaitaire",
    # "estime" ou "contrat". Détermine la base du profit réel et le
    # défaut « refacturable » des achats.
    billing_kind: str = "forfaitaire"

    service_lines: List[CostLine]   # from soumission items
    material_lines: List[CostLine]  # from achats
    invoiced_amount: float
    # Facturé HORS TAXES (somme des subtotals des factures émises).
    invoiced_amount_ex_tax: float = 0.0
    # Sous-total facturé en EXTRAS (FactureItem.kind == 'extra') — ne
    # compte pas dans le « reste à facturer » du contrat. Sert de
    # revenu additionnel dans le calcul du profit réel.
    extras_billed_amount: float = 0.0
    # Rabais facturé sur la base (HT et TTC, valeurs absolues). Réduit le
    # « reste à facturer » : un rabais est une baisse volontaire du prix,
    # pas du travail non facturé.
    rabais_billed_amount: float = 0.0
    rabais_billed_amount_ttc: float = 0.0
    paid_amount: float
    balance_due: float
    # Taxes COLLECTÉES sur les factures émises (à remettre au
    # gouvernement). TPS = fédéral (Receveur général), TVQ = Revenu
    # Québec. La somme représente l'obligation fiscale brute du projet
    # (avant déduction des CTI/RTI sur les achats — non gérés ici).
    tps_collected: float = 0.0
    tvq_collected: float = 0.0
    taxes_collected: float = 0.0
    # Bloc « taxes à remettre » — base = montant FACTURÉ HT (pas le contrat).
    # perçue = facturé HT × taux ; CTI/RTI = matériel HT taxé × taux ;
    # net = perçue − récupérée. Se recalcule à chaque facture/avenant/rabais.
    facture_ht_base: float = 0.0
    tps_percue: float = 0.0
    tvq_percue: float = 0.0
    tps_paid_on_purchases: float = 0.0   # CTI (TPS récupérée sur achats)
    tvq_paid_on_purchases: float = 0.0   # RTI (TVQ récupérée sur achats)
    net_tps_to_remit: float = 0.0
    net_tvq_to_remit: float = 0.0
    net_taxes_to_remit: float = 0.0
    invoices: List[InvoiceLine]


@router.get(
    "/{project_id}/finances",
    response_model=FinancesResponse,
    summary="Financial projection vs actuals for a project",
)
async def get_finances(
    project_id: int,
    db: DBSession,
    _: CurrentUser,
) -> FinancesResponse:
    try:
        return await _compute_finances(project_id, db)
    except HTTPException:
        raise
    except Exception as exc:
        # Surface l'erreur côté Render logs avec traceback complet
        # pour le diagnostic (le front voit déjà le message via le
        # détail HTTP).
        log.exception(
            "GET /projects/%s/finances failed: %s", project_id, exc
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"finances_failed: {type(exc).__name__}: {exc}",
        )


async def _compute_finances(
    project_id: int, db
) -> "FinancesResponse":
    proj = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    # --- Projected from the linked soumission's items ---
    # Coût projeté des services = NOS coûts (cost_per_unit interne), PAS
    # le prix de vente au client. Affichés taxes incluses (TTC) — c'est
    # ce qu'on débourse réellement chez le fournisseur. Le profit, lui,
    # se calcule hors taxes (voir plus bas).
    service_lines: List[CostLine] = []
    projected_revenue = 0.0
    service_cost_ht = 0.0
    service_cost_ttc = 0.0
    billing_kind = "forfaitaire"
    sm: Optional[Soumission] = None
    items: list = []

    if proj.soumission_id:
        items = list(
            (
                await db.execute(
                    select(SoumissionItem).where(
                        SoumissionItem.soumission_id == proj.soumission_id
                    )
                )
            ).scalars().all()
        )
        for it in items:
            qty = float(it.quantity)
            cpu = float(it.cost_per_unit or 0)  # coût interne unitaire HT
            factor = 1.0
            if bool(it.tps_applicable):
                factor += TPS_RATE
            if bool(it.tvq_applicable):
                factor += TVQ_RATE
            line_ht = qty * cpu
            line_ttc = round(line_ht * factor, 2)
            service_cost_ht += line_ht
            service_cost_ttc += line_ttc
            service_lines.append(
                CostLine(
                    label=(it.description or f"Item #{it.id}"),
                    quantity=qty,
                    unit_cost=round(cpu * factor, 2),
                    total=line_ttc,
                )
            )
        sm = (
            await db.execute(
                select(Soumission).where(Soumission.id == proj.soumission_id)
            )
        ).scalar_one_or_none()
        if sm is not None:
            billing_kind = (
                "contrat"
                if (sm.kind or "") == "contract"
                else (sm.pricing_kind or "forfaitaire")
            )

    # Revenu contractuel = total de la soumission (TTC) si liée, sinon
    # le budget du projet (synchronisé sur la soumission, ou saisi
    # manuellement). C'est le « montant de la soumission » du calcul de
    # profit. Sans cette retombée sur le budget, un projet sans
    # soumission liée affichait un revenu nul → profit = −coûts.
    if sm is not None and sm.total is not None:
        projected_revenue = float(sm.total)
    elif proj.budget is not None:
        projected_revenue = float(proj.budget)
    elif items:
        projected_revenue = sum(float(it.total) for it in items)

    # Revenu HORS TAXES (assiette du profit). ATTENTION : le sous-total
    # STOCKÉ de la soumission peut avoir dérivé et contenir un montant
    # TAXES INCLUSES (bug observé : la carte « Soumission acceptée (HT) »
    # affichait le total TTC, p. ex. 30 112,65 au lieu du HT ~26 190).
    # La source de vérité est donc les ITEMS : le sous-total HT = somme
    # des lignes (prix de vente HT, déjà net des rabais), exactement ce
    # qu'affiche la fiche soumission. On ne retombe sur le sous-total
    # stocké, puis sur une dérivation 1.14975, QUE si la soumission n'a
    # pas d'items (forfait / contrat / import legacy).
    if items:
        projected_revenue_ex_tax = round(
            sum(float(it.total or 0) for it in items), 2
        )
    elif sm is not None and sm.subtotal is not None:
        projected_revenue_ex_tax = float(sm.subtotal)
    elif projected_revenue > 0:
        projected_revenue_ex_tax = ht_from_ttc(projected_revenue)
    else:
        projected_revenue_ex_tax = 0.0

    # Affiché dans la carte « Coût projeté » : services TTC.
    projected_service_cost = round(service_cost_ttc, 2)

    # --- Projected labour ---
    # Heuristique :
    #   1. heures = somme des phases (duration_days × 8h × jours
    #      ouvrables / jours calendaires) × nombre de personnes
    #      assignées au projet (membres ProjectMember + assignees de
    #      phase distincts). Au minimum 1 personne pour qu'une phase
    #      compte.
    #   2. Si aucune phase, fallback à start_date/end_date du projet
    #      × 8 h × 1 personne (jours ouvrables seulement).
    #   3. Si l'utilisateur a saisi estimated_hours_override, on
    #      l'utilise directement (override total).
    #   4. coût = somme(heures attribuées à chaque personne × taux
    #      réel avec primes CNESST/CCQ). Pour les phases assignées à
    #      un sous-traitant, on multiplie par leur taux propre. Pour
    #      les phases sans assignee précis on utilise la moyenne des
    #      coûts réels des membres du projet.
    avg_rate_stmt = select(func.coalesce(func.avg(Employe.hourly_rate), 35.0))
    avg_rate = float((await db.execute(avg_rate_stmt)).scalar_one() or 35.0)

    def _real_cost_for_employe(emp: Optional[Employe]) -> float:
        """Coût horaire réel = base × (1 + cnesst + ccq actif)."""
        if emp is None:
            return float(avg_rate)
        base = float(emp.hourly_rate or avg_rate)
        cnesst = float(emp.cnesst_rate or 0)
        ccq = float(emp.ccq_rate or 0) if bool(emp.is_ccq) else 0.0
        return round(base * (1.0 + cnesst + ccq), 2)

    def _business_days(start, end) -> int:
        """Compte les jours lundi-vendredi inclus dans [start, end]."""
        from datetime import timedelta as _td

        if start is None or end is None or end < start:
            return 0
        d = start
        n = 0
        while d <= end:
            if d.weekday() < 5:
                n += 1
            d = d + _td(days=1)
        return n

    # Membres du projet (ProjectMember.user_id → email → Employe)
    members_emails: list[str] = []
    if True:
        member_users = (
            await db.execute(
                select(User)
                .join(ProjectMember, ProjectMember.user_id == User.id)
                .where(ProjectMember.project_id == project_id)
            )
        ).scalars().all()
        members_emails = [u.email for u in member_users if u.email]

    members_employes: list[Employe] = []
    if members_emails:
        members_employes = list(
            (
                await db.execute(
                    select(Employe).where(Employe.email.in_(members_emails))
                )
            ).scalars().all()
        )

    # Phases du projet (avec leurs assignees éventuels)
    phases = (
        await db.execute(
            select(ProjectPhase)
            .where(ProjectPhase.project_id == project_id)
            .order_by(ProjectPhase.position.asc())
        )
    ).scalars().all()

    projected_labour_hours = 0.0
    projected_labour_cost = 0.0

    if phases:
        # Coût moyen "réel" des membres du projet — fallback pour les
        # phases sans aucun assignee précis (cas legacy).
        if members_employes:
            members_avg_cost = round(
                sum(_real_cost_for_employe(m) for m in members_employes)
                / len(members_employes),
                2,
            )
        else:
            members_avg_cost = float(avg_rate)

        # Pré-charge les employés assignés (N-M) à chaque phase pour
        # ne pas faire 1 query par phase. Les sous-traitants n'entrent
        # pas dans la main-d'œuvre planifiée — leurs heures et leur
        # coût sont portés par leur propre contrat.
        from app.models.project_assignees import ProjectPhaseAssignee as _PPA

        phase_assignees_emp: dict[int, set[int]] = {}
        if phases:
            pa_rows = (
                await db.execute(
                    select(_PPA).where(
                        _PPA.phase_id.in_([p.id for p in phases]),
                        _PPA.employe_id.is_not(None),
                    )
                )
            ).scalars().all()
            for pa in pa_rows:
                phase_assignees_emp.setdefault(pa.phase_id, set()).add(
                    pa.employe_id
                )

        # Sous-traitants payés À L'HEURE assignés aux phases : leur coût
        # planifié entre dans la main-d'œuvre projetée (heures × nb
        # travailleurs × taux horaire de leur fiche). Les sous-traitants
        # au forfait (hourly_billed=False) restent exclus — leur coût est
        # porté par leur propre contrat.
        phase_hourly_subs: dict[int, list[tuple[float, int]]] = {}
        if phases:
            from app.models.sous_traitant import SousTraitant as _ST

            st_rows = (
                await db.execute(
                    select(
                        _PPA.phase_id,
                        _PPA.sous_traitant_id,
                        _PPA.worker_count,
                    ).where(
                        _PPA.phase_id.in_([p.id for p in phases]),
                        _PPA.sous_traitant_id.is_not(None),
                        _PPA.hourly_billed.is_(True),
                    )
                )
            ).all()
            st_ids = {int(r[1]) for r in st_rows}
            st_rates: dict[int, float] = {}
            if st_ids:
                rate_rows = (
                    await db.execute(
                        select(_ST.id, _ST.hourly_rate).where(
                            _ST.id.in_(st_ids)
                        )
                    )
                ).all()
                st_rates = {int(i): float(r or 0) for i, r in rate_rows}
            for phase_id, st_id, wc in st_rows:
                rate = st_rates.get(int(st_id), 0.0)
                if rate > 0:
                    phase_hourly_subs.setdefault(int(phase_id), []).append(
                        (rate, int(wc or 1))
                    )

        for ph in phases:
            # duration_days est décimal (Numeric 6,2) : la planification
            # autorise les demi-journées et fractions — 0.5 j = 4 h,
            # 1.25 j = 10 h. On NE tronque PAS : un int() ferait
            # disparaître les demi-journées (0.5 → 0, phase ignorée) et
            # arrondirait 1.75 j à 1 j. Les heures prévues doivent
            # refléter la planification réelle, journée par journée.
            days = float(ph.duration_days or 0)
            if days <= 0:
                continue
            hours = days * 8

            # Sous-traitants à l'heure de cette phase — comptés même si
            # AUCUN employé n'est assigné (phase confiée 100 % en
            # sous-traitance). Doit rester avant le `continue` ci-dessous.
            for st_rate, st_wc in phase_hourly_subs.get(ph.id, []):
                sub_h = hours * max(1, st_wc)
                projected_labour_hours += sub_h
                projected_labour_cost += sub_h * st_rate

            # Main-d'œuvre planifiée = EMPLOYÉS Horizon assignés à la
            # phase (legacy single + N-M moderne). Aucun employé sur la
            # phase — qu'elle soit confiée à un sous-traitant ou non
            # encore assignée — = 0 h de main-d'œuvre planifiée. On ne
            # devine pas de personne par défaut : la main-d'œuvre
            # Horizon doit être assignée explicitement.
            emp_ids: set[int] = set(phase_assignees_emp.get(ph.id, set()))
            if ph.assignee_employe_id:
                emp_ids.add(ph.assignee_employe_id)
            if not emp_ids:
                continue

            # Coût horaire : moyenne des taux réels des employés assignés.
            emps = (
                await db.execute(
                    select(Employe).where(Employe.id.in_(emp_ids))
                )
            ).scalars().all()
            rates = [_real_cost_for_employe(e) for e in emps]
            cost_per_hour = (
                round(sum(rates) / len(rates), 2)
                if rates else members_avg_cost
            )
            persons = len(emp_ids)

            phase_hours = hours * persons
            projected_labour_hours += phase_hours
            projected_labour_cost += phase_hours * cost_per_hour
    elif proj.start_date and proj.end_date:
        # Fallback ancien comportement, mais en jours OUVRABLES seulement.
        biz_days = max(1, _business_days(proj.start_date, proj.end_date))
        persons = max(1, len(members_employes))
        if members_employes:
            avg_real = (
                sum(_real_cost_for_employe(m) for m in members_employes)
                / len(members_employes)
            )
        else:
            avg_real = float(avg_rate)
        projected_labour_hours = biz_days * 8 * persons
        projected_labour_cost = projected_labour_hours * avg_real

    # Override manuel : si l'utilisateur a fixé un nombre d'heures, on
    # garde le coût horaire moyen calculé ci-dessus mais on remplace
    # les heures.
    override = (
        float(proj.estimated_hours_override)
        if getattr(proj, "estimated_hours_override", None) is not None
        else None
    )
    if override is not None:
        rate = (
            (projected_labour_cost / projected_labour_hours)
            if projected_labour_hours > 0
            else float(avg_rate)
        )
        projected_labour_hours = override
        projected_labour_cost = override * rate

    projected_labour_hours = round(projected_labour_hours, 2)
    projected_labour_cost = round(projected_labour_cost, 2)

    # Carte « Coût projeté » : services TTC + main-d'œuvre (sans taxe de
    # vente — la paie/CNESST/CCQ ne portent pas de TPS/TVQ).
    projected_total_cost = round(
        service_cost_ttc + projected_labour_cost, 2
    )
    # Coût projeté HORS TAXES — sert UNIQUEMENT au calcul du profit.
    projected_total_cost_ht = round(
        service_cost_ht + projected_labour_cost, 2
    )
    # Profit = revenu HORS TAXES − coût HORS TAXES. Les TPS/TVQ ne sont
    # ni un revenu (perçues pour le gouvernement) ni un coût net (CTI/RTI
    # récupérables), donc on calcule le profit hors taxes des deux côtés.
    projected_profit = round(
        projected_revenue_ex_tax - projected_total_cost_ht, 2
    )
    projected_margin_pct = (
        round(projected_profit / projected_revenue_ex_tax * 100, 1)
        if projected_revenue_ex_tax > 0
        else 0.0
    )

    # --- Actuals ---
    achats_stmt = select(Achat).where(Achat.project_id == project_id)
    achats = (await db.execute(achats_stmt)).scalars().all()

    # Coût réel matériel = HT + taxes payées au fournisseur (TTC) — on
    # affiche ce qui a vraiment été déboursé sur le compte de la compagnie.
    material_lines = [
        CostLine(
            label=(a.description or a.reference or f"Achat #{a.id}"),
            quantity=1,
            unit_cost=float(a.amount or 0) + float(a.amount_taxes or 0),
            total=float(a.amount or 0) + float(a.amount_taxes or 0),
        )
        for a in achats
    ]
    actual_material_cost = round(
        sum(m.total for m in material_lines), 2
    )  # TTC affiché
    # Nos fournisseurs sont TOUS inscrits aux taxes : la taxe payée sur les
    # matériaux est récupérable (CTI/RTI) et n'est donc PAS un coût. Le
    # coût réel matériel HORS TAXES = TTC / 1.14975 ; il sert aussi de base
    # aux CTI/RTI récupérables dans le bloc « taxes à remettre ».
    actual_material_cost_ht = ht_from_ttc(actual_material_cost)
    recoverable_materials_ht = actual_material_cost_ht

    # Labour — sum of approved punches on this project
    punches = (
        await db.execute(
            select(Punch).where(
                Punch.project_id == project_id,
                Punch.ended_at.is_not(None),
            )
        )
    ).scalars().all()
    actual_labour_hours = sum(float(p.hours or 0) for p in punches)

    # Pull each punched employé's REAL cost (with CNESST + CCQ) and
    # total individually. C'est le coût qui charge réellement le projet.
    #
    # IMPORTANT — coût daté : on utilise le taux EN VIGUEUR à la date
    # du punch (historique des salaires), pas le taux courant. Ainsi un
    # changement de salaire ne réécrit pas la rentabilité passée.
    from app.services.employe_rates import (
        load_rate_periods,
        resolve_real_cost,
    )

    punch_emp_ids = [p.employe_id for p in punches if p.employe_id]
    rate_periods = await load_rate_periods(db, punch_emp_ids)
    emp_cache: dict[int, Optional[Employe]] = {}

    actual_labour_cost = 0.0
    for p in punches:
        emp = emp_cache.get(p.employe_id)
        if p.employe_id not in emp_cache:
            emp = (
                await db.execute(
                    select(Employe).where(Employe.id == p.employe_id)
                )
            ).scalar_one_or_none()
            emp_cache[p.employe_id] = emp
        punch_date = (
            p.started_at.date() if p.started_at is not None else None
        )
        cost_per_hour = resolve_real_cost(
            rate_periods.get(p.employe_id or -1, []),
            punch_date,
            emp,
            float(avg_rate),
        )
        actual_labour_cost += float(p.hours or 0) * cost_per_hour
    actual_labour_cost = round(actual_labour_cost, 2)

    # TTC pour l'affichage de la carte « Coût actuel ».
    actual_total_cost = round(actual_material_cost + actual_labour_cost, 2)
    # HORS TAXES pour le calcul du profit + l'avancement du contrat.
    actual_total_cost_ht = round(
        actual_material_cost_ht + actual_labour_cost, 2
    )

    # Invoicing — liste des factures du projet avec leur statut, total
    # et montant payé. Sert à la fois aux totaux agrégés et au listing
    # détaillé côté UI (« suivre les factures réellement envoyées »).
    factures = (
        await db.execute(
            select(Facture)
            .where(Facture.project_id == project_id)
            .order_by(Facture.issued_at.desc().nulls_last(), Facture.id.desc())
        )
    ).scalars().all()

    # Self-heal : si une facture a son total NULL ou désynchro vs ses
    # items, on le recalcule à la volée. Évite que les KPI projet
    # (« Facturé », « Reste à facturer ») affichent 0 quand la
    # facture a été créée avant l'auto-recompute (PR #396) OU quand
    # un item a été modifié hors de notre endpoint (import QBO, etc.).
    if factures:
        from app.api.v1.endpoints.facture_items import (
            _recompute_facture_totals,
        )

        for f in factures:
            if not (f.total and f.total > 0):
                await _recompute_facture_totals(db, f.id)
        # Rafraîchit pour avoir les nouveaux totaux.
        await db.flush()
        ids = [f.id for f in factures]
        factures = (
            await db.execute(
                select(Facture)
                .where(Facture.id.in_(ids))
                .order_by(Facture.issued_at.desc().nulls_last(), Facture.id.desc())
            )
        ).scalars().all()

    # Factures qui COMPTENT dans le « facturé » et le profit : seulement
    # celles RÉELLEMENT ENVOYÉES au client (sent / paid / overdue). Les
    # BROUILLONS (draft) et annulées (void) ne sont pas du revenu → exclues
    # des totaux et du calcul de profit. (La liste détaillée, elle, montre
    # quand même tout, brouillons inclus.)
    _BILLED_STATUSES = {
        FactureStatus.SENT.value,
        FactureStatus.PAID.value,
        FactureStatus.OVERDUE.value,
    }
    billed_factures = [
        f for f in factures if (f.status or "") in _BILLED_STATUSES
    ]

    # Sépare l'invoiced en 2 buckets : « contrat » (items kind=service|
    # rabais|frais) et « extras » (items kind=extra). Les extras n'ont
    # pas à compter dans le « reste à facturer » du contrat car ils
    # sont hors-soumission.
    extras_subtotal = 0.0
    contract_subtotal = 0.0
    rabais_subtotal = 0.0  # lignes « rabais » (négatives) sur la base
    if billed_factures:
        from app.models.facture_item import FactureItem as _FI

        items_rows = (
            await db.execute(
                select(_FI.facture_id, _FI.total, _FI.kind).where(
                    _FI.facture_id.in_([f.id for f in billed_factures])
                )
            )
        ).all()
        for _fid, _it_total, _it_kind in items_rows:
            v = float(_it_total or 0)
            if _it_kind == "extra":
                extras_subtotal += v
            else:
                contract_subtotal += v
                if _it_kind == "rabais":
                    rabais_subtotal += v
    # Rabais facturé sur la base (valeur absolue, HT). Un rabais est une
    # réduction VOLONTAIRE du prix : il ne doit pas créer un faux « reste
    # à facturer ». On l'expose pour que le reste à facturer le déduise
    # (le rabais réduit le montant à facturer / la soumission).
    rabais_billed_amount = round(abs(rabais_subtotal), 2)
    rabais_billed_amount_ttc = round(rabais_billed_amount * TAX_FACTOR, 2)
    # Les taxes ne changent pas la répartition contrat/extras au
    # niveau sous-total ; on calcule l'invoiced TTC total comme avant
    # pour les KPI cash-flow (Facturé / Reçu / Solde).
    invoiced = sum(float(f.total or 0) for f in billed_factures)

    # Facturé HT et taxes collectées — séparés pour calcul du profit
    # (HT) et pour afficher l'obligation fiscale (à remettre au gouv).
    invoiced_ex_tax = round(
        sum(float(f.subtotal or 0) for f in billed_factures), 2
    )
    tps_collected = round(sum(float(f.tps or 0) for f in billed_factures), 2)
    tvq_collected = round(sum(float(f.tvq or 0) for f in billed_factures), 2)
    taxes_collected = round(tps_collected + tvq_collected, 2)

    # Taxes NETTES à remettre — base = montant FACTURÉ HT (factures émises,
    # hors brouillons), PAS le total du contrat. Perçue = facturé HT × taux ;
    # récupérée (CTI/RTI) = matériel HT taxé × taux ; net = perçue − récupérée.
    # Se recalcule à chaque facture / avenant / rabais. N'entre jamais dans
    # le profit.
    _tx = taxes_to_remit(invoiced_ex_tax, recoverable_materials_ht)
    facture_ht_base = _tx["facture_ht"]
    tps_percue = _tx["tps_percue"]
    tvq_percue = _tx["tvq_percue"]
    tps_paid_on_purchases = _tx["cti"]
    tvq_paid_on_purchases = _tx["rti"]
    net_tps_to_remit = _tx["net_tps"]
    net_tvq_to_remit = _tx["net_tvq"]
    net_taxes_to_remit_total = _tx["total"]

    # Extras facturés (avant taxes) — exposé séparément à l'UI.
    extras_billed_amount = round(extras_subtotal, 2)

    # Paiements par facture (un seul SELECT, on group puis on lookup).
    paid_by_facture: dict[int, float] = {}
    if factures:
        ids = [f.id for f in factures]
        rows = (
            await db.execute(
                select(
                    Payment.facture_id,
                    func.coalesce(func.sum(Payment.amount), 0),
                )
                .where(Payment.facture_id.in_(ids))
                .group_by(Payment.facture_id)
            )
        ).all()
        for fid, amt in rows:
            paid_by_facture[int(fid)] = float(amt or 0)

    # Construit les InvoiceLine + agrège paid_sum
    invoices_out: List[InvoiceLine] = []
    paid_sum = 0.0
    for f in factures:
        paid_for_this = paid_by_facture.get(f.id, 0.0)
        # Fallback : facture marquée payée mais sans rangées Payment
        # → on compte son total comme reçu (évite le double-compte).
        if (
            f.status == FactureStatus.PAID.value
            and f.paid_at is not None
            and paid_for_this == 0
        ):
            paid_for_this = float(f.total or 0)
        paid_sum += paid_for_this
        invoices_out.append(
            InvoiceLine(
                id=f.id,
                reference=f.reference,
                status=f.status,
                total=round(float(f.total or 0), 2),
                issued_at=f.issued_at,
                due_at=f.due_at,
                paid_at=f.paid_at,
                paid_amount=round(paid_for_this, 2),
            )
        )

    balance = max(0.0, invoiced - paid_sum)

    # Profit réel — assiette de revenu selon le type de soumission :
    #   • FORFAITAIRE : prix fixe garanti. Revenu = soumission HT +
    #     extras facturés HT (travaux ajoutés hors-contrat). Le profit
    #     vient de la maîtrise des coûts sous le prix fixe.
    #   • ESTIMÉ / À CONTRAT (refacturable) : on facture en fonction du
    #     réel. Revenu = montant RÉELLEMENT facturé HT (contrat + extras,
    #     déjà inclus dans invoiced_ex_tax). Profit = facturé − coût réel.
    # Les taxes (TPS/TVQ) ne sont jamais incluses : remises au
    # gouvernement, exposées séparément via `taxes_collected`. Coût pris
    # hors taxes (CTI/RTI récupérables).
    if billing_kind == "forfaitaire":
        revenue_base = projected_revenue_ex_tax + extras_billed_amount
    else:
        revenue_base = invoiced_ex_tax
    actual_profit = round(revenue_base - actual_total_cost_ht, 2)
    actual_margin_pct = (
        round(actual_profit / revenue_base * 100, 1)
        if revenue_base > 0 else 0.0
    )

    return FinancesResponse(
        projected_revenue=round(projected_revenue, 2),
        projected_revenue_ex_tax=round(projected_revenue_ex_tax, 2),
        projected_service_cost=round(projected_service_cost, 2),
        projected_labour_cost=projected_labour_cost,
        projected_labour_hours=round(projected_labour_hours, 2),
        projected_total_cost=projected_total_cost,
        projected_profit=projected_profit,
        projected_margin_pct=projected_margin_pct,
        actual_material_cost=round(actual_material_cost, 2),
        actual_material_cost_ht=round(actual_material_cost_ht, 2),
        actual_labour_cost=actual_labour_cost,
        actual_labour_hours=round(actual_labour_hours, 2),
        actual_total_cost=actual_total_cost,
        actual_total_cost_ht=actual_total_cost_ht,
        actual_profit=actual_profit,
        actual_margin_pct=actual_margin_pct,
        billing_kind=billing_kind,
        service_lines=service_lines,
        material_lines=material_lines,
        invoiced_amount=round(invoiced, 2),
        invoiced_amount_ex_tax=invoiced_ex_tax,
        extras_billed_amount=extras_billed_amount,
        rabais_billed_amount=rabais_billed_amount,
        rabais_billed_amount_ttc=rabais_billed_amount_ttc,
        paid_amount=round(paid_sum, 2),
        balance_due=round(balance, 2),
        tps_collected=tps_collected,
        tvq_collected=tvq_collected,
        taxes_collected=taxes_collected,
        facture_ht_base=facture_ht_base,
        tps_percue=tps_percue,
        tvq_percue=tvq_percue,
        tps_paid_on_purchases=tps_paid_on_purchases,
        tvq_paid_on_purchases=tvq_paid_on_purchases,
        net_tps_to_remit=net_tps_to_remit,
        net_tvq_to_remit=net_tvq_to_remit,
        net_taxes_to_remit=net_taxes_to_remit_total,
        invoices=invoices_out,
    )


@router.get(
    "/{project_id}/statement.pdf",
    summary="État de compte du projet en PDF (relevé client)",
)
async def get_project_statement_pdf(
    project_id: int,
    db: DBSession,
    _: CurrentUser,
    include_facture_id: Optional[int] = None,
) -> Response:
    """Relevé autonome consultable à tout moment : factures envoyées,
    paiements reçus, total des factures et solde dû — le même état de
    compte que celui transmis au client.

    ``?include_facture_id=`` inclut une facture précise même en brouillon
    (prévisualisation depuis la fiche de cette facture, p. ex. la facture
    finale qu'on s'apprête à envoyer)."""
    from app.services.facture_pdf import render_statement_pdf

    rendered = await render_statement_pdf(
        db, project_id, include_facture_id=include_facture_id
    )
    if rendered is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Projet introuvable"
        )
    project, pdf_bytes = rendered
    filename = f"etat-de-compte-projet-{project.id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


class StatementSendResult(BaseModel):
    sent: bool
    to: str


@router.post(
    "/{project_id}/statement/send",
    response_model=StatementSendResult,
    summary="Envoyer l'état de compte du projet au client (PDF par courriel)",
)
async def send_project_statement(
    project_id: int,
    db: DBSession,
    _: CurrentUser,
) -> StatementSendResult:
    """Rend l'état de compte du projet et l'envoie au client par courriel
    (avec la copie de supervision en BCC, gérée par le mailer). Rendu
    synchrone : on confirme l'envoi dans la réponse."""
    from app.integrations.email_graph import EmailAttachment, get_mailer
    from app.models.client import Client
    from app.services.facture_pdf import render_statement_pdf

    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable")
    if project.client_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Ce projet n'a pas de client associé.",
        )
    client = (
        await db.execute(select(Client).where(Client.id == project.client_id))
    ).scalar_one_or_none()
    if client is None or not client.email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Le client n'a pas d'adresse courriel.",
        )

    mailer = get_mailer()
    if not mailer.ready:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Le service courriel n'est pas configuré.",
        )

    rendered = await render_statement_pdf(db, project_id)
    if rendered is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Impossible de générer l'état de compte.",
        )
    _project, pdf_bytes = rendered

    is_en = (getattr(client, "language", "fr") or "fr") == "en"
    subject = (
        "Account statement — Horizon Services Immobiliers"
        if is_en
        else "État de compte — Horizon Services Immobiliers"
    )
    body = (
        "<p>Hello,</p><p>Please find attached the current "
        "account statement for your project.</p>"
        if is_en
        else "<p>Bonjour,</p><p>Vous trouverez ci-joint "
        "l'état de compte à jour de votre projet.</p>"
    )
    try:
        await mailer.send(
            to=[client.email],
            subject=subject,
            html_body=body,
            reply_to=mailer.sender,
            attachments=[
                EmailAttachment(
                    name="etat-de-compte.pdf",
                    content_bytes=pdf_bytes,
                    content_type="application/pdf",
                )
            ],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Envoi état de compte (projet %s) échoué : %s",
            project_id,
            exc,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Échec de l'envoi du courriel : {exc}",
        )
    return StatementSendResult(sent=True, to=client.email)
