"""Heures pointées sur UN projet, détaillées PAR EMPLOYÉ (Construction).

Demande du partenaire de Phil (2026-07-10) : suivre les heures des employés
punchés sur un projet. Les totaux existaient (finances/cockpit) mais rien
n'exposait la décomposition par employé ni le détail des punchs.

    GET /api/v1/projects/{project_id}/punches-summary

Réponse : total du projet + par employé (heures, nb de punchs, heures
approuvées / en attente, dernier punch) + le détail des punchs de chaque
employé (récents d'abord) pour l'accordéon de la fiche projet.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.employe import Employe
from app.models.project import Project
from app.models.punch import Punch

router = APIRouter(prefix="/projects", tags=["project-punches"])

#: Borne de sécurité — un projet n'a jamais des milliers de punchs.
_MAX_PUNCHES = 1000


class PunchDetail(BaseModel):
    id: int
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    hours: float = 0
    task: Optional[str] = None
    approved: bool = False


class EmployeHours(BaseModel):
    employe_id: int
    full_name: str
    total_hours: float
    punch_count: int
    approved_hours: float
    pending_hours: float
    last_punch_at: Optional[datetime] = None
    punches: List[PunchDetail]


class ProjectPunchesSummary(BaseModel):
    project_id: int
    total_hours: float
    employes: List[EmployeHours]


@router.get(
    "/{project_id}/punches-summary",
    response_model=ProjectPunchesSummary,
)
async def project_punches_summary(
    project_id: int, db: DBSession, _: CurrentUser
) -> ProjectPunchesSummary:
    proj = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Projet introuvable."
        )

    punches = (
        (
            await db.execute(
                select(Punch)
                .where(
                    Punch.project_id == project_id,
                    Punch.hours.is_not(None),
                )
                .order_by(Punch.started_at.desc())
                .limit(_MAX_PUNCHES)
            )
        )
        .scalars()
        .all()
    )

    # Noms des employés concernés (une requête).
    emp_ids = {p.employe_id for p in punches if p.employe_id}
    names: dict[int, str] = {}
    if emp_ids:
        emps = (
            (
                await db.execute(
                    select(Employe).where(Employe.id.in_(emp_ids))
                )
            )
            .scalars()
            .all()
        )
        names = {e.id: e.full_name for e in emps}

    by_emp: dict[int, list[Punch]] = {}
    for p in punches:
        if not p.employe_id:
            continue
        by_emp.setdefault(p.employe_id, []).append(p)

    out: list[EmployeHours] = []
    total_hours = 0.0
    for emp_id, plist in by_emp.items():
        hours = round(sum(float(p.hours or 0) for p in plist), 2)
        approved = round(
            sum(float(p.hours or 0) for p in plist if p.approved), 2
        )
        total_hours += hours
        out.append(
            EmployeHours(
                employe_id=emp_id,
                full_name=names.get(emp_id, f"Employé #{emp_id}"),
                total_hours=hours,
                punch_count=len(plist),
                approved_hours=approved,
                pending_hours=round(hours - approved, 2),
                last_punch_at=plist[0].started_at if plist else None,
                punches=[
                    PunchDetail(
                        id=p.id,
                        started_at=p.started_at,
                        ended_at=p.ended_at,
                        hours=float(p.hours or 0),
                        task=p.task,
                        approved=bool(p.approved),
                    )
                    for p in plist
                ],
            )
        )

    # Plus gros contributeurs en premier.
    out.sort(key=lambda e: -e.total_hours)
    return ProjectPunchesSummary(
        project_id=project_id,
        total_hours=round(total_hours, 2),
        employes=out,
    )
