"""Financial breakdown for a Project: projected (from soumission items
+ agenda-planned labour) vs actual (from achats + approved punches).

    GET /api/v1/projects/{project_id}/finances
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

log = logging.getLogger(__name__)

from app.api.deps import CurrentUser, DBSession
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
from app.models.sous_traitant import SousTraitant
from app.models.user import User


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
    projected_service_cost: float
    projected_labour_cost: float
    projected_labour_hours: float
    projected_total_cost: float
    projected_profit: float
    projected_margin_pct: float

    actual_material_cost: float
    actual_labour_cost: float
    actual_labour_hours: float
    actual_total_cost: float
    actual_profit: Optional[float]  # null while no facture is paid yet
    actual_margin_pct: Optional[float]

    service_lines: List[CostLine]   # from soumission items
    material_lines: List[CostLine]  # from achats
    invoiced_amount: float
    paid_amount: float
    balance_due: float
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
    service_lines: List[CostLine] = []
    projected_revenue = 0.0
    if proj.soumission_id:
        items = (
            await db.execute(
                select(SoumissionItem).where(
                    SoumissionItem.soumission_id == proj.soumission_id
                )
            )
        ).scalars().all()
        for it in items:
            service_lines.append(
                CostLine(
                    label=it.description,
                    quantity=float(it.quantity),
                    unit_cost=float(it.unit_price),
                    total=float(it.total),
                )
            )
        # projected revenue = facture client (soumission total if set else sum items)
        sm = (
            await db.execute(
                select(Soumission).where(Soumission.id == proj.soumission_id)
            )
        ).scalar_one_or_none()
        if sm and sm.total is not None:
            projected_revenue = float(sm.total)
        else:
            projected_revenue = sum(it.total for it in service_lines)

    projected_service_cost = sum(it.total for it in service_lines)

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
        # phases non-assignées explicitement.
        if members_employes:
            members_avg_cost = round(
                sum(_real_cost_for_employe(m) for m in members_employes)
                / len(members_employes),
                2,
            )
        else:
            members_avg_cost = float(avg_rate)

        for ph in phases:
            days = int(ph.duration_days or 0)
            if days <= 0:
                continue
            hours = days * 8

            # Quel coût appliquer ?
            cost_per_hour = members_avg_cost
            if ph.assignee_employe_id:
                emp = (
                    await db.execute(
                        select(Employe).where(
                            Employe.id == ph.assignee_employe_id
                        )
                    )
                ).scalar_one_or_none()
                cost_per_hour = _real_cost_for_employe(emp)
            elif ph.assignee_sous_traitant_id:
                # Pour un sous-traitant on prend hourly_rate (s'il existe
                # dans le modèle SousTraitant) — sinon avg_rate.
                st = (
                    await db.execute(
                        select(SousTraitant).where(
                            SousTraitant.id == ph.assignee_sous_traitant_id
                        )
                    )
                ).scalar_one_or_none()
                st_rate = (
                    float(getattr(st, "hourly_rate", None) or avg_rate)
                    if st
                    else float(avg_rate)
                )
                cost_per_hour = st_rate

            # Multiplier par le nombre de personnes : si un assignee
            # explicite, c'est 1 ; sinon membres du projet (au moins 1).
            persons = 1
            if not ph.assignee_employe_id and not ph.assignee_sous_traitant_id:
                persons = max(1, len(members_employes))

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

    projected_total_cost = round(
        projected_service_cost + projected_labour_cost, 2
    )
    projected_profit = round(projected_revenue - projected_total_cost, 2)
    projected_margin_pct = (
        round(projected_profit / projected_revenue * 100, 1)
        if projected_revenue > 0
        else 0.0
    )

    # --- Actuals ---
    achats_stmt = select(Achat).where(Achat.project_id == project_id)
    achats = (await db.execute(achats_stmt)).scalars().all()
    material_lines = [
        CostLine(
            label=a.description or a.reference,
            quantity=1,
            unit_cost=float(a.amount or 0),
            total=float(a.amount or 0),
        )
        for a in achats
    ]
    actual_material_cost = sum(m.total for m in material_lines)

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
    actual_labour_cost = 0.0
    for p in punches:
        emp = (
            await db.execute(
                select(Employe).where(Employe.id == p.employe_id)
            )
        ).scalar_one_or_none()
        actual_labour_cost += float(p.hours or 0) * _real_cost_for_employe(emp)
    actual_labour_cost = round(actual_labour_cost, 2)

    actual_total_cost = round(actual_material_cost + actual_labour_cost, 2)

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
    invoiced = sum(float(f.total or 0) for f in factures)

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

    # Actual profit = paid revenue - costs (only meaningful once paid)
    actual_profit: Optional[float] = None
    actual_margin_pct: Optional[float] = None
    if paid_sum > 0:
        actual_profit = round(paid_sum - actual_total_cost, 2)
        actual_margin_pct = (
            round(actual_profit / paid_sum * 100, 1) if paid_sum > 0 else 0.0
        )

    return FinancesResponse(
        projected_revenue=round(projected_revenue, 2),
        projected_service_cost=round(projected_service_cost, 2),
        projected_labour_cost=projected_labour_cost,
        projected_labour_hours=round(projected_labour_hours, 2),
        projected_total_cost=projected_total_cost,
        projected_profit=projected_profit,
        projected_margin_pct=projected_margin_pct,
        actual_material_cost=round(actual_material_cost, 2),
        actual_labour_cost=actual_labour_cost,
        actual_labour_hours=round(actual_labour_hours, 2),
        actual_total_cost=actual_total_cost,
        actual_profit=actual_profit,
        actual_margin_pct=actual_margin_pct,
        service_lines=service_lines,
        material_lines=material_lines,
        invoiced_amount=round(invoiced, 2),
        paid_amount=round(paid_sum, 2),
        balance_due=round(balance, 2),
        invoices=invoices_out,
    )
