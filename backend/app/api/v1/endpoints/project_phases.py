"""Project phases — ordered stages of a project with a start date
and a duration in days. Tasks can be nested inside a phase via
ProjectTask.phase_id.

    GET    /api/v1/projects/{project_id}/phases
    POST   /api/v1/projects/{project_id}/phases
    PATCH  /api/v1/projects/{project_id}/phases/{phase_id}
    DELETE /api/v1/projects/{project_id}/phases/{phase_id}
    PUT    /api/v1/projects/{project_id}/phases/reorder  (bulk reorder)

Assignations multi-personnes:
Les phases peuvent être assignées à plusieurs employés + plusieurs
sous-traitants simultanément via la table de jointure
`project_phase_assignees`. Les payloads acceptent `assignee_employe_ids`
et `assignee_sous_traitant_ids` (listes). Les anciens champs scalaires
`assignee_employe_id` / `assignee_sous_traitant_id` restent lisibles
(= premier id de la liste) pour préserver les clients existants.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DBSession
from app.core.permissions import visible_project_ids
from app.models.project import Project
from app.models.project_assignees import ProjectPhaseAssignee
from app.models.project_phase import ProjectPhase


router = APIRouter(prefix="/projects", tags=["project-phases"])


class PhaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    position: int = Field(default=0, ge=0)
    start_date: Optional[date] = None
    duration_days: Optional[int] = Field(default=None, ge=0, le=3650)
    notes: Optional[str] = None
    # Legacy scalar fields — toujours acceptés pour compat. Si les
    # listes ci-dessous sont fournies, elles priment.
    assignee_employe_id: Optional[int] = Field(default=None, gt=0)
    assignee_sous_traitant_id: Optional[int] = Field(default=None, gt=0)
    assignee_employe_ids: Optional[List[int]] = None
    assignee_sous_traitant_ids: Optional[List[int]] = None


class PhaseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    position: Optional[int] = Field(default=None, ge=0)
    start_date: Optional[date] = None
    duration_days: Optional[int] = Field(default=None, ge=0, le=3650)
    notes: Optional[str] = None
    assignee_employe_id: Optional[int] = None
    assignee_sous_traitant_id: Optional[int] = None
    assignee_employe_ids: Optional[List[int]] = None
    assignee_sous_traitant_ids: Optional[List[int]] = None


class PhaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    name: str
    position: int
    start_date: Optional[date]
    duration_days: Optional[int]
    notes: Optional[str]
    # Champs scalaires legacy — renseignés au « primary » assignee
    # (= premier employé / sous-traitant de la liste) pour que les
    # vieux consumers continuent de fonctionner.
    assignee_employe_id: Optional[int] = None
    assignee_sous_traitant_id: Optional[int] = None
    # Nouveaux champs — vérités de référence.
    assignee_employe_ids: List[int] = Field(default_factory=list)
    assignee_sous_traitant_ids: List[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ReorderBody(BaseModel):
    phase_ids: List[int]


async def _ensure_project_visible(
    db, project_id: int, user
) -> Project:
    visible = await visible_project_ids(db, user)
    if visible is not None and project_id not in visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    p = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return p


async def _load_assignee_ids(
    db, phase_ids: List[int]
) -> dict[int, tuple[List[int], List[int]]]:
    """Return {phase_id: (employe_ids, sous_traitant_ids)} for the
    given phases, based on the project_phase_assignees join table."""
    if not phase_ids:
        return {}
    rows = (
        await db.execute(
            select(
                ProjectPhaseAssignee.phase_id,
                ProjectPhaseAssignee.employe_id,
                ProjectPhaseAssignee.sous_traitant_id,
            ).where(ProjectPhaseAssignee.phase_id.in_(phase_ids))
        )
    ).all()
    out: dict[int, tuple[List[int], List[int]]] = {
        pid: ([], []) for pid in phase_ids
    }
    for phase_id, emp_id, st_id in rows:
        emps, sts = out[int(phase_id)]
        if emp_id is not None:
            emps.append(int(emp_id))
        if st_id is not None:
            sts.append(int(st_id))
    for pid in out:
        out[pid][0].sort()
        out[pid][1].sort()
    return out


def _phase_read(
    ph: ProjectPhase,
    assignee_employe_ids: List[int],
    assignee_sous_traitant_ids: List[int],
) -> PhaseRead:
    # Legacy scalars = « primary » assignee, c.-à-d. première entrée
    # de la liste. Permet à tous les lecteurs existants de continuer
    # de fonctionner en attendant qu'ils migrent vers les listes.
    primary_emp = (
        assignee_employe_ids[0] if assignee_employe_ids else None
    )
    primary_st = (
        assignee_sous_traitant_ids[0]
        if assignee_sous_traitant_ids
        else None
    )
    return PhaseRead(
        id=ph.id,
        project_id=ph.project_id,
        name=ph.name,
        position=ph.position,
        start_date=ph.start_date,
        duration_days=ph.duration_days,
        notes=ph.notes,
        assignee_employe_id=primary_emp,
        assignee_sous_traitant_id=primary_st,
        assignee_employe_ids=assignee_employe_ids,
        assignee_sous_traitant_ids=assignee_sous_traitant_ids,
        created_at=ph.created_at,
        updated_at=ph.updated_at,
    )


async def _replace_assignees(
    db,
    phase: ProjectPhase,
    employe_ids: Optional[List[int]],
    sous_traitant_ids: Optional[List[int]],
) -> None:
    """Remplace les assignations d'une phase à partir des listes
    fournies. None = ne touche pas. Liste vide = retire tous les
    assignés de ce type. Maintient également les champs legacy
    (`assignee_employe_id`, `assignee_sous_traitant_id`) en phase avec
    le « primary » assignee."""
    if employe_ids is not None:
        await db.execute(
            delete(ProjectPhaseAssignee).where(
                ProjectPhaseAssignee.phase_id == phase.id,
                ProjectPhaseAssignee.employe_id.is_not(None),
            )
        )
        for emp_id in dict.fromkeys(employe_ids):  # dedup, keep order
            db.add(
                ProjectPhaseAssignee(
                    phase_id=phase.id, employe_id=int(emp_id)
                )
            )
        phase.assignee_employe_id = (
            int(employe_ids[0]) if employe_ids else None
        )
    if sous_traitant_ids is not None:
        await db.execute(
            delete(ProjectPhaseAssignee).where(
                ProjectPhaseAssignee.phase_id == phase.id,
                ProjectPhaseAssignee.sous_traitant_id.is_not(None),
            )
        )
        for st_id in dict.fromkeys(sous_traitant_ids):
            db.add(
                ProjectPhaseAssignee(
                    phase_id=phase.id, sous_traitant_id=int(st_id)
                )
            )
        phase.assignee_sous_traitant_id = (
            int(sous_traitant_ids[0]) if sous_traitant_ids else None
        )
    await db.flush()


def _resolve_lists(
    data_legacy_employe: Optional[int],
    data_legacy_sous_traitant: Optional[int],
    data_employe_ids: Optional[List[int]],
    data_sous_traitant_ids: Optional[List[int]],
) -> tuple[Optional[List[int]], Optional[List[int]]]:
    """Cohabite legacy (scalaires) + nouveaux (listes) dans les
    payloads. La liste l'emporte si fournie ; sinon on fabrique une
    liste à un élément à partir du scalaire."""
    emp_list: Optional[List[int]]
    if data_employe_ids is not None:
        emp_list = [int(x) for x in data_employe_ids]
    elif data_legacy_employe is not None:
        emp_list = [int(data_legacy_employe)]
    else:
        emp_list = None

    st_list: Optional[List[int]]
    if data_sous_traitant_ids is not None:
        st_list = [int(x) for x in data_sous_traitant_ids]
    elif data_legacy_sous_traitant is not None:
        st_list = [int(data_legacy_sous_traitant)]
    else:
        st_list = None
    return emp_list, st_list


@router.get(
    "/{project_id}/phases",
    response_model=List[PhaseRead],
)
async def list_phases(
    project_id: int, db: DBSession, user: CurrentUser
) -> List[PhaseRead]:
    await _ensure_project_visible(db, project_id, user)
    rows = (
        await db.execute(
            select(ProjectPhase)
            .where(ProjectPhase.project_id == project_id)
            .order_by(ProjectPhase.position.asc(), ProjectPhase.id.asc())
        )
    ).scalars().all()
    assignees = await _load_assignee_ids(db, [r.id for r in rows])
    return [
        _phase_read(r, *assignees.get(r.id, ([], [])))
        for r in rows
    ]


@router.post(
    "/{project_id}/phases",
    response_model=PhaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_phase(
    project_id: int,
    data: PhaseCreate,
    db: DBSession,
    user: CurrentUser,
) -> PhaseRead:
    await _ensure_project_visible(db, project_id, user)
    # Default position: append at the end.
    if data.position == 0:
        last = (
            await db.execute(
                select(ProjectPhase.position)
                .where(ProjectPhase.project_id == project_id)
                .order_by(ProjectPhase.position.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        pos = (int(last) + 1) if last is not None else 0
    else:
        pos = data.position
    emp_list, st_list = _resolve_lists(
        data.assignee_employe_id,
        data.assignee_sous_traitant_id,
        data.assignee_employe_ids,
        data.assignee_sous_traitant_ids,
    )
    ph = ProjectPhase(
        project_id=project_id,
        name=data.name.strip(),
        position=pos,
        start_date=data.start_date,
        duration_days=data.duration_days,
        notes=(data.notes.strip() if data.notes else None),
        assignee_employe_id=(emp_list[0] if emp_list else None),
        assignee_sous_traitant_id=(st_list[0] if st_list else None),
    )
    db.add(ph)
    await db.flush()
    await _replace_assignees(db, ph, emp_list, st_list)
    await db.refresh(ph)
    assignees = await _load_assignee_ids(db, [ph.id])
    return _phase_read(ph, *assignees.get(ph.id, ([], [])))


@router.patch(
    "/{project_id}/phases/{phase_id}",
    response_model=PhaseRead,
)
async def update_phase(
    project_id: int,
    phase_id: int,
    data: PhaseUpdate,
    db: DBSession,
    user: CurrentUser,
) -> PhaseRead:
    await _ensure_project_visible(db, project_id, user)
    ph = (
        await db.execute(
            select(ProjectPhase).where(
                ProjectPhase.id == phase_id,
                ProjectPhase.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if ph is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Phase not found")

    fields = data.model_dump(exclude_unset=True)
    # On traite les assignations séparément via _replace_assignees.
    fields.pop("assignee_employe_ids", None)
    fields.pop("assignee_sous_traitant_ids", None)
    # Les legacy scalaires restent acceptés, mais seront écrasés par
    # _replace_assignees si une liste a été fournie.
    legacy_emp = fields.pop("assignee_employe_id", None)
    legacy_st = fields.pop("assignee_sous_traitant_id", None)

    for field, value in fields.items():
        setattr(ph, field, value)
    await db.flush()

    has_legacy_update = (
        "assignee_employe_id" in data.model_fields_set
        or "assignee_sous_traitant_id" in data.model_fields_set
    )
    has_list_update = (
        "assignee_employe_ids" in data.model_fields_set
        or "assignee_sous_traitant_ids" in data.model_fields_set
    )
    if has_list_update or has_legacy_update:
        emp_list, st_list = _resolve_lists(
            legacy_emp if "assignee_employe_id" in data.model_fields_set else None,
            legacy_st if "assignee_sous_traitant_id" in data.model_fields_set else None,
            data.assignee_employe_ids,
            data.assignee_sous_traitant_ids,
        )
        await _replace_assignees(db, ph, emp_list, st_list)

    await db.refresh(ph)
    assignees = await _load_assignee_ids(db, [ph.id])
    return _phase_read(ph, *assignees.get(ph.id, ([], [])))


@router.delete(
    "/{project_id}/phases/{phase_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_phase(
    project_id: int,
    phase_id: int,
    db: DBSession,
    user: CurrentUser,
) -> None:
    await _ensure_project_visible(db, project_id, user)
    ph = (
        await db.execute(
            select(ProjectPhase).where(
                ProjectPhase.id == phase_id,
                ProjectPhase.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if ph is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Phase not found")
    await db.delete(ph)
    await db.flush()


@router.put(
    "/{project_id}/phases/reorder",
    response_model=List[PhaseRead],
)
async def reorder_phases(
    project_id: int,
    data: ReorderBody,
    db: DBSession,
    user: CurrentUser,
) -> List[PhaseRead]:
    """Bulk reorder: accepts an ordered list of phase IDs and writes
    their new `position` in one pass. Phases not mentioned keep their
    existing position (bumped to the end)."""
    await _ensure_project_visible(db, project_id, user)
    rows = (
        await db.execute(
            select(ProjectPhase).where(
                ProjectPhase.project_id == project_id
            )
        )
    ).scalars().all()
    by_id = {r.id: r for r in rows}
    pos = 0
    for pid in data.phase_ids:
        ph = by_id.get(pid)
        if ph is None:
            continue
        ph.position = pos
        pos += 1
    # Orphans go after the explicit order to preserve them.
    for ph in rows:
        if ph.id not in set(data.phase_ids):
            ph.position = pos
            pos += 1
    await db.flush()
    rows_sorted = sorted(
        rows, key=lambda r: (r.position, r.id)
    )
    assignees = await _load_assignee_ids(db, [r.id for r in rows_sorted])
    return [
        _phase_read(r, *assignees.get(r.id, ([], [])))
        for r in rows_sorted
    ]


# ---------------------------------------------------------------------------
# Bulk listing — used by the agenda timeline (Par chantier / Par personne).
# Returns every phase the current user can see, across all visible projects.
# Kept on a separate router prefix so the URL is /api/v1/phases (flat).
# ---------------------------------------------------------------------------

phases_router = APIRouter(prefix="/phases", tags=["project-phases"])


@phases_router.get("", response_model=List[PhaseRead])
async def list_all_phases(
    db: DBSession, user: CurrentUser
) -> List[PhaseRead]:
    visible = await visible_project_ids(db, user)
    stmt = select(ProjectPhase).order_by(
        ProjectPhase.project_id.asc(),
        ProjectPhase.position.asc(),
        ProjectPhase.id.asc(),
    )
    if visible is not None:
        if not visible:
            return []
        stmt = stmt.where(ProjectPhase.project_id.in_(visible))
    rows = (await db.execute(stmt)).scalars().all()
    assignees = await _load_assignee_ids(db, [r.id for r in rows])
    return [
        _phase_read(r, *assignees.get(r.id, ([], [])))
        for r in rows
    ]
