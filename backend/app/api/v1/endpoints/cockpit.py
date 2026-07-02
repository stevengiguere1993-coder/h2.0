"""Cockpit chargé de projet — vue d'ensemble du pôle Construction.

GET /api/v1/cockpit/overview (manager+) : agrège en UNE réponse tout ce
qu'un chargé de projet (Oli) doit surveiller — santé des projets actifs
(budget vs dépensé réel = achats + main-d'œuvre au coût), bons de
travail internes actifs (âge, urgence, heures), PO envoyés en attente
de facture fournisseur. Le temps réel « qui est où » vit déjà dans
GET /punch/live — le front appelle les deux.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DBSession, RequireManager

router = APIRouter(prefix="/cockpit", tags=["cockpit"])


class CockpitProject(BaseModel):
    id: int
    name: str
    client_name: Optional[str] = None
    address: Optional[str] = None
    status: str
    responsible_user_id: Optional[int] = None
    responsible_name: Optional[str] = None
    budget: Optional[float] = None
    soumission_total: Optional[float] = None
    spent_achats: float = 0
    spent_labor: float = 0
    hours: float = 0
    # Phase couvrant aujourd'hui (planif en cours), sinon null.
    phase_name: Optional[str] = None
    # Toutes les phases planifiées sont finies et le projet n'est pas
    # livré → dernière phase + nb de jours depuis sa fin.
    late_phase_name: Optional[str] = None
    late_days: int = 0
    awaiting_signature: bool = False
    has_signed_bon: bool = False
    correction_bon_draft: bool = False
    correction_status: str = "a_planifier"
    last_activity_at: Optional[datetime] = None
    workers_now: list[str] = Field(default_factory=list)


class CockpitBon(BaseModel):
    id: int
    reference: str
    title: str
    address: Optional[str] = None
    status: str
    is_urgent: bool = False
    executant_type: Optional[str] = None
    amount: Optional[float] = None
    age_days: int = 0
    hours: float = 0
    workers_now: list[str] = Field(default_factory=list)


class CockpitPO(BaseModel):
    id: int
    reference: str
    fournisseur_name: Optional[str] = None
    amount_max: Optional[float] = None
    sent_at: Optional[datetime] = None


class CockpitOverview(BaseModel):
    projects: list[CockpitProject]
    bons: list[CockpitBon]
    po_sent: list[CockpitPO]


ACTIVE_PROJECT_STATUSES = (
    "planned",
    "ready_to_start",
    "in_progress",
    "suspended",
    "correction",
)

# Coût horaire par défaut quand l'employé n'a pas de taux (aligné sur le
# 35 $/h utilisé par le moteur de refacturation des bons).
DEFAULT_HOURLY_COST = 35.0


@router.get(
    "/overview",
    response_model=CockpitOverview,
    summary="Vue d'ensemble chargé de projet (manager+)",
)
async def cockpit_overview(
    db: DBSession, _: RequireManager
) -> CockpitOverview:
    from app.models.achat import Achat
    from app.models.bon_travail import BonTravail
    from app.models.client import Client
    from app.models.employe import Employe
    from app.models.project import Project
    from app.models.project_phase import ProjectPhase
    from app.models.punch import Punch
    from app.models.purchase_order import PurchaseOrder
    from app.models.soumission import Soumission
    from app.models.user import User

    today = date.today()

    # ── Projets actifs (chantiers clients — pas les ordres de travail) ──
    projects = (
        await db.execute(
            select(Project).where(
                Project.status.in_(ACTIVE_PROJECT_STATUSES),
                Project.kind == "construction",
            )
        )
    ).scalars().all()
    proj_ids = [p.id for p in projects]

    # Libellés clients / responsables / totaux de soumission (batch).
    client_names: dict = {}
    cl_ids = {p.client_id for p in projects if p.client_id}
    if cl_ids:
        rows = (
            await db.execute(
                select(Client.id, Client.name).where(Client.id.in_(cl_ids))
            )
        ).all()
        client_names = {r[0]: r[1] for r in rows}

    resp_names: dict = {}
    resp_ids = {p.responsible_user_id for p in projects if p.responsible_user_id}
    if resp_ids:
        rows = (
            await db.execute(
                select(
                    User.id, User.first_name, User.last_name, User.email
                ).where(User.id.in_(resp_ids))
            )
        ).all()
        for uid, fn, ln, email in rows:
            name = " ".join(x for x in [fn, ln] if x).strip()
            resp_names[uid] = name or email

    sm_totals: dict = {}
    sm_ids = {p.soumission_id for p in projects if p.soumission_id}
    if sm_ids:
        rows = (
            await db.execute(
                select(Soumission.id, Soumission.total).where(
                    Soumission.id.in_(sm_ids)
                )
            )
        ).all()
        sm_totals = {r[0]: float(r[1]) for r in rows if r[1] is not None}

    # ── Dépenses réelles : achats par projet ────────────────────────────
    achats_by_proj: dict = {}
    last_achat_by_proj: dict = {}
    if proj_ids:
        rows = (
            await db.execute(
                select(
                    Achat.project_id,
                    func.sum(Achat.amount),
                    func.max(Achat.created_at),
                )
                .where(
                    Achat.project_id.in_(proj_ids),
                    Achat.status != "cancelled",
                )
                .group_by(Achat.project_id)
            )
        ).all()
        for pid, total, last in rows:
            achats_by_proj[pid] = float(total or 0)
            last_achat_by_proj[pid] = last

    # ── Main-d'œuvre : heures × coût employé (fallback 35 $) ────────────
    emp_rates: dict = {}
    emp_names: dict = {}
    emps = (await db.execute(select(Employe))).scalars().all()
    for e in emps:
        emp_names[e.id] = e.full_name
        try:
            emp_rates[e.id] = (
                float(e.hourly_rate) if e.hourly_rate else DEFAULT_HOURLY_COST
            )
        except (TypeError, ValueError):
            emp_rates[e.id] = DEFAULT_HOURLY_COST

    hours_by_proj: dict = {}
    labor_by_proj: dict = {}
    last_punch_by_proj: dict = {}
    if proj_ids:
        rows = (
            await db.execute(
                select(
                    Punch.project_id,
                    Punch.employe_id,
                    func.sum(Punch.hours),
                    func.max(Punch.started_at),
                )
                .where(
                    Punch.project_id.in_(proj_ids),
                    Punch.hours.is_not(None),
                )
                .group_by(Punch.project_id, Punch.employe_id)
            )
        ).all()
        for pid, emp_id, hrs, last in rows:
            h = float(hrs or 0)
            hours_by_proj[pid] = hours_by_proj.get(pid, 0.0) + h
            labor_by_proj[pid] = labor_by_proj.get(pid, 0.0) + h * emp_rates.get(
                emp_id, DEFAULT_HOURLY_COST
            )
            prev = last_punch_by_proj.get(pid)
            if last is not None and (prev is None or last > prev):
                last_punch_by_proj[pid] = last

    # ── Qui est dessus en ce moment (punchs ouverts) ────────────────────
    open_punches = (
        await db.execute(select(Punch).where(Punch.ended_at.is_(None)))
    ).scalars().all()
    workers_proj: dict = {}
    workers_bon: dict = {}
    for p in open_punches:
        name = emp_names.get(p.employe_id)
        if not name:
            continue
        if p.project_id:
            workers_proj.setdefault(p.project_id, []).append(name)
        if p.bon_travail_id:
            workers_bon.setdefault(p.bon_travail_id, []).append(name)
        # Un punch ouvert compte comme activité du projet.
        if p.project_id:
            prev = last_punch_by_proj.get(p.project_id)
            if prev is None or (p.started_at and p.started_at > prev):
                last_punch_by_proj[p.project_id] = p.started_at

    # ── Phases : en cours aujourd'hui / toutes finies (retard) ──────────
    phase_current: dict = {}
    phase_last_end: dict = {}
    phase_last_name: dict = {}
    phase_has_future: dict = {}
    if proj_ids:
        phases = (
            await db.execute(
                select(ProjectPhase).where(
                    ProjectPhase.project_id.in_(proj_ids),
                    ProjectPhase.start_date.is_not(None),
                )
            )
        ).scalars().all()
        for ph in phases:
            days = max(math.ceil(float(ph.duration_days or 1)), 1)
            end = ph.start_date + timedelta(days=days - 1)
            if ph.start_date <= today <= end:
                phase_current.setdefault(ph.project_id, ph.name)
            if ph.start_date > today:
                phase_has_future[ph.project_id] = True
            prev_end = phase_last_end.get(ph.project_id)
            if prev_end is None or end > prev_end:
                phase_last_end[ph.project_id] = end
                phase_last_name[ph.project_id] = ph.name

    # ── Signature des bons liés (mêmes règles que le kanban) ────────────
    awaiting: set = set()
    signed: set = set()
    draft_correction: set = set()
    if proj_ids:
        rows = (
            await db.execute(
                select(
                    BonTravail.project_id,
                    BonTravail.origin,
                    BonTravail.sent_at,
                    BonTravail.signed_at,
                ).where(BonTravail.project_id.in_(proj_ids))
            )
        ).all()
        for pid, origin, sent_at, signed_at in rows:
            if pid is None:
                continue
            if signed_at is not None:
                signed.add(pid)
            elif sent_at is not None:
                awaiting.add(pid)
            elif (origin or "") == "correction":
                draft_correction.add(pid)

    out_projects: list[CockpitProject] = []
    for p in projects:
        last_p = last_punch_by_proj.get(p.id)
        last_a = last_achat_by_proj.get(p.id)
        last_activity = max(
            [d for d in (last_p, last_a) if d is not None], default=None
        )
        cur_phase = phase_current.get(p.id)
        late_name = None
        late_days = 0
        if (
            cur_phase is None
            and not phase_has_future.get(p.id)
            and phase_last_end.get(p.id) is not None
            and phase_last_end[p.id] < today
        ):
            late_name = phase_last_name.get(p.id)
            late_days = (today - phase_last_end[p.id]).days
        out_projects.append(
            CockpitProject(
                id=p.id,
                name=p.name,
                client_name=client_names.get(p.client_id),
                address=p.address,
                status=p.status,
                responsible_user_id=p.responsible_user_id,
                responsible_name=resp_names.get(p.responsible_user_id),
                budget=float(p.budget) if p.budget is not None else None,
                soumission_total=sm_totals.get(p.soumission_id),
                spent_achats=round(achats_by_proj.get(p.id, 0.0), 2),
                spent_labor=round(labor_by_proj.get(p.id, 0.0), 2),
                hours=round(hours_by_proj.get(p.id, 0.0), 2),
                phase_name=cur_phase,
                late_phase_name=late_name,
                late_days=late_days,
                awaiting_signature=p.id in awaiting,
                has_signed_bon=p.id in signed,
                correction_bon_draft=p.id in draft_correction,
                correction_status=getattr(
                    p, "correction_status", "a_planifier"
                )
                or "a_planifier",
                last_activity_at=last_activity,
                workers_now=sorted(workers_proj.get(p.id, [])),
            )
        )
    # En cours d'abord, puis par nom.
    status_rank = {s: i for i, s in enumerate(ACTIVE_PROJECT_STATUSES)}
    out_projects.sort(
        key=lambda x: (status_rank.get(x.status, 9), x.name.lower())
    )

    # ── Bons de travail internes actifs ─────────────────────────────────
    bons = (
        await db.execute(
            select(BonTravail).where(
                BonTravail.kind == "interne",
                BonTravail.status.notin_(["facture", "cancelled"]),
            )
        )
    ).scalars().all()
    bon_ids = [b.id for b in bons]
    hours_by_bon: dict = {}
    if bon_ids:
        rows = (
            await db.execute(
                select(Punch.bon_travail_id, func.sum(Punch.hours))
                .where(
                    Punch.bon_travail_id.in_(bon_ids),
                    Punch.hours.is_not(None),
                )
                .group_by(Punch.bon_travail_id)
            )
        ).all()
        hours_by_bon = {r[0]: float(r[1] or 0) for r in rows}

    out_bons: list[CockpitBon] = []
    for b in bons:
        created = b.created_at.date() if b.created_at else today
        out_bons.append(
            CockpitBon(
                id=b.id,
                reference=b.reference,
                title=b.title,
                address=b.address,
                status=b.status,
                is_urgent=bool(getattr(b, "is_urgent", False)),
                executant_type=b.executant_type,
                amount=float(b.amount) if b.amount is not None else None,
                age_days=max((today - created).days, 0),
                hours=round(hours_by_bon.get(b.id, 0.0), 2),
                workers_now=sorted(workers_bon.get(b.id, [])),
            )
        )
    out_bons.sort(
        key=lambda x: (not x.is_urgent, -x.age_days, x.reference.lower())
    )

    # ── PO envoyés (facture fournisseur à récupérer) ────────────────────
    pos = (
        await db.execute(
            select(PurchaseOrder).where(PurchaseOrder.status == "sent")
        )
    ).scalars().all()
    fr_names: dict = {}
    fr_ids = {po.fournisseur_id for po in pos if po.fournisseur_id}
    if fr_ids:
        from app.models.fournisseur import Fournisseur

        rows = (
            await db.execute(
                select(Fournisseur.id, Fournisseur.name).where(
                    Fournisseur.id.in_(fr_ids)
                )
            )
        ).all()
        fr_names = {r[0]: r[1] for r in rows}
    out_pos = [
        CockpitPO(
            id=po.id,
            reference=po.reference,
            fournisseur_name=fr_names.get(po.fournisseur_id),
            amount_max=(
                float(po.amount_max) if po.amount_max is not None else None
            ),
            sent_at=po.sent_at,
        )
        for po in pos
    ]
    out_pos.sort(key=lambda x: (x.sent_at or datetime.min).isoformat())

    return CockpitOverview(
        projects=out_projects, bons=out_bons, po_sent=out_pos
    )
