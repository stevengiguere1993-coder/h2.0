"""Leave requests (congés) workflow.

    GET    /api/v1/leaves                   — admin list (+ filters)
    GET    /api/v1/leaves/mine              — my own requests (PWA)
    POST   /api/v1/leaves                   — employee submits a request
    POST   /api/v1/leaves/{id}/approve      — admin approves (creates agenda block)
    POST   /api/v1/leaves/{id}/reject       — admin rejects
    POST   /api/v1/leaves/{id}/cancel       — employee cancels their pending request
    GET    /api/v1/leaves/pending-count     — badge count for the admin topbar

When a leave is approved, an AgendaEvent of type "conge" is created
and linked back via LeaveRequest.agenda_event_id. If the leave is
later rejected or cancelled, the linked event is deleted so the
employee's agenda is freed up.

Notifications:
 - Submit -> email every admin user
 - Approve / reject -> email the employee
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.integrations.email_graph import get_mailer
from app.models.agenda_event import AgendaEvent
from app.models.employe import Employe
from app.models.leave_request import LeaveRequest, LeaveStatus
from app.models.user import User


log = logging.getLogger(__name__)


router = APIRouter(prefix="/leaves", tags=["leave-requests"])


class LeaveCreate(BaseModel):
    start_at: datetime
    end_at: datetime
    reason: Optional[str] = Field(default=None, max_length=500)


class LeaveReview(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


class LeaveRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employe_id: int
    employe_name: Optional[str] = None
    start_at: datetime
    end_at: datetime
    reason: Optional[str]
    status: str
    reviewed_by_user_id: Optional[int]
    reviewed_at: Optional[datetime]
    review_note: Optional[str]
    agenda_event_id: Optional[int]
    created_at: datetime


async def _resolve_employe(db, user_email: str) -> Optional[Employe]:
    if not user_email:
        return None
    stmt = select(Employe).where(
        func.lower(Employe.email) == user_email.lower(),
        Employe.active.is_(True),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _to_read(db, lr: LeaveRequest) -> LeaveRead:
    data = LeaveRead.model_validate(lr)
    emp = (
        await db.execute(select(Employe).where(Employe.id == lr.employe_id))
    ).scalar_one_or_none()
    if emp is not None:
        data.employe_name = emp.full_name
    return data


async def _notify_admins(
    *, subject: str, html_body: str
) -> None:
    """Email every active admin user. Best effort."""
    mailer = get_mailer()
    if not mailer.ready:
        return
    # We accept the async context manager leakage for this rare call.
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        admins = (
            await db.execute(
                select(User).where(
                    User.is_admin.is_(True), User.is_active.is_(True)
                )
            )
        ).scalars().all()
        recipients = [a.email for a in admins if a.email]
    if not recipients:
        return
    try:
        await mailer.send(
            to=recipients, subject=subject, html_body=html_body
        )
    except Exception as exc:
        log.exception("Failed admin leave notification: %s", exc)


async def _notify_employee(
    *, employe: Employe, subject: str, html_body: str
) -> None:
    mailer = get_mailer()
    if not mailer.ready or not employe.email:
        return
    try:
        await mailer.send(
            to=[employe.email], subject=subject, html_body=html_body
        )
    except Exception as exc:
        log.exception("Failed employee leave notification: %s", exc)


def _fmt_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---- employee-facing ----

@router.post("", response_model=LeaveRead, status_code=status.HTTP_201_CREATED)
async def create_leave(
    body: LeaveCreate,
    db: DBSession,
    user: CurrentUser,
    bg: BackgroundTasks,
) -> LeaveRead:
    emp = await _resolve_employe(db, user.email)
    if emp is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Aucun employé n'est lié à ce compte (email).",
        )
    if body.end_at <= body.start_at:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Plage horaire invalide."
        )
    lr = LeaveRequest(
        employe_id=emp.id,
        start_at=body.start_at,
        end_at=body.end_at,
        reason=(body.reason.strip() if body.reason else None),
        status=LeaveStatus.PENDING.value,
    )
    db.add(lr)
    await db.flush()
    await db.refresh(lr)

    # Fire-and-forget admin notification so the response is fast.
    bg.add_task(
        _notify_admins,
        subject=f"Nouvelle demande de congé — {emp.full_name}",
        html_body=(
            f"<div style='font-family:Helvetica,Arial,sans-serif;color:#111'>"
            f"<p>{emp.full_name} a demandé un congé :</p>"
            f"<ul>"
            f"<li>Début : {_fmt_dt(body.start_at)}</li>"
            f"<li>Fin : {_fmt_dt(body.end_at)}</li>"
            f"{'<li>Raison : ' + body.reason + '</li>' if body.reason else ''}"
            f"</ul>"
            f"<p>Approuve ou refuse depuis le portail :"
            f" <a href='https://immohorizon.com/fr/app/conges'>"
            f"immohorizon.com/fr/app/conges</a></p></div>"
        ),
    )

    return await _to_read(db, lr)


@router.get("/mine", response_model=List[LeaveRead])
async def my_leaves(
    db: DBSession,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> List[LeaveRead]:
    emp = await _resolve_employe(db, user.email)
    if emp is None:
        return []
    rows = (
        await db.execute(
            select(LeaveRequest)
            .where(LeaveRequest.employe_id == emp.id)
            .order_by(LeaveRequest.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    out: List[LeaveRead] = []
    for r in rows:
        out.append(await _to_read(db, r))
    return out


@router.post("/{leave_id}/cancel", response_model=LeaveRead)
async def cancel_leave(
    leave_id: int,
    db: DBSession,
    user: CurrentUser,
) -> LeaveRead:
    emp = await _resolve_employe(db, user.email)
    if emp is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Employé inconnu.")
    lr = (
        await db.execute(select(LeaveRequest).where(LeaveRequest.id == leave_id))
    ).scalar_one_or_none()
    if lr is None or lr.employe_id != emp.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demande introuvable.")
    if lr.status not in (
        LeaveStatus.PENDING.value,
        LeaveStatus.APPROVED.value,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Demande déjà traitée."
        )
    # If it had an agenda block, delete it.
    if lr.agenda_event_id:
        ev = (
            await db.execute(
                select(AgendaEvent).where(
                    AgendaEvent.id == lr.agenda_event_id
                )
            )
        ).scalar_one_or_none()
        if ev is not None:
            await db.delete(ev)
        lr.agenda_event_id = None
    lr.status = LeaveStatus.CANCELLED.value
    await db.flush()
    await db.refresh(lr)
    return await _to_read(db, lr)


# ---- admin-facing ----

@router.get("", response_model=List[LeaveRead])
async def list_leaves(
    db: DBSession,
    user: CurrentUser,
    status_filter: Optional[str] = Query(
        default=None, alias="status", pattern="^(pending|approved|rejected|cancelled)$"
    ),
    employe_id: Optional[int] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> List[LeaveRead]:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin requis.")
    stmt = select(LeaveRequest)
    if status_filter:
        stmt = stmt.where(LeaveRequest.status == status_filter)
    if employe_id is not None:
        stmt = stmt.where(LeaveRequest.employe_id == employe_id)
    stmt = stmt.order_by(LeaveRequest.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    out: List[LeaveRead] = []
    for r in rows:
        out.append(await _to_read(db, r))
    return out


@router.get("/pending-count", response_model=int)
async def pending_count(db: DBSession, user: CurrentUser) -> int:
    if not user.is_admin:
        return 0
    n = (
        await db.execute(
            select(func.count(LeaveRequest.id)).where(
                LeaveRequest.status == LeaveStatus.PENDING.value
            )
        )
    ).scalar_one()
    return int(n or 0)


@router.post("/{leave_id}/approve", response_model=LeaveRead)
async def approve_leave(
    leave_id: int,
    body: LeaveReview,
    db: DBSession,
    user: CurrentUser,
    bg: BackgroundTasks,
) -> LeaveRead:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin requis.")
    lr = (
        await db.execute(select(LeaveRequest).where(LeaveRequest.id == leave_id))
    ).scalar_one_or_none()
    if lr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demande introuvable.")
    if lr.status != LeaveStatus.PENDING.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Demande déjà traitée."
        )
    emp = (
        await db.execute(select(Employe).where(Employe.id == lr.employe_id))
    ).scalar_one_or_none()

    lr.status = LeaveStatus.APPROVED.value
    lr.reviewed_by_user_id = user.id
    lr.reviewed_at = datetime.now(timezone.utc)
    lr.review_note = (body.note.strip() if body.note else None)

    # Create the agenda block (event_type=conge) and link it back.
    if emp is not None:
        ev = AgendaEvent(
            title=f"Congé — {emp.full_name}",
            description=lr.reason,
            start_at=lr.start_at,
            end_at=lr.end_at,
            all_day=False,
            assignee_id=emp.id,
            event_type="conge",
        )
        db.add(ev)
        await db.flush()
        await db.refresh(ev)
        lr.agenda_event_id = ev.id

    await db.flush()
    await db.refresh(lr)

    if emp is not None:
        bg.add_task(
            _notify_employee,
            employe=emp,
            subject="Congé approuvé ✅",
            html_body=(
                f"<div style='font-family:Helvetica,Arial,sans-serif;color:#111'>"
                f"<p>Bonjour {emp.full_name},</p>"
                f"<p>Ta demande de congé est <strong>approuvée</strong>.</p>"
                f"<ul>"
                f"<li>Début : {_fmt_dt(lr.start_at)}</li>"
                f"<li>Fin : {_fmt_dt(lr.end_at)}</li>"
                f"{'<li>Note : ' + (lr.review_note or '') + '</li>' if lr.review_note else ''}"
                f"</ul>"
                f"<p>Bon repos !</p>"
                f"</div>"
            ),
        )

    return await _to_read(db, lr)


@router.post("/{leave_id}/reject", response_model=LeaveRead)
async def reject_leave(
    leave_id: int,
    body: LeaveReview,
    db: DBSession,
    user: CurrentUser,
    bg: BackgroundTasks,
) -> LeaveRead:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin requis.")
    lr = (
        await db.execute(select(LeaveRequest).where(LeaveRequest.id == leave_id))
    ).scalar_one_or_none()
    if lr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demande introuvable.")
    if lr.status != LeaveStatus.PENDING.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Demande déjà traitée."
        )
    emp = (
        await db.execute(select(Employe).where(Employe.id == lr.employe_id))
    ).scalar_one_or_none()

    lr.status = LeaveStatus.REJECTED.value
    lr.reviewed_by_user_id = user.id
    lr.reviewed_at = datetime.now(timezone.utc)
    lr.review_note = (body.note.strip() if body.note else None)
    await db.flush()
    await db.refresh(lr)

    if emp is not None:
        bg.add_task(
            _notify_employee,
            employe=emp,
            subject="Demande de congé refusée",
            html_body=(
                f"<div style='font-family:Helvetica,Arial,sans-serif;color:#111'>"
                f"<p>Bonjour {emp.full_name},</p>"
                f"<p>Ta demande de congé du {_fmt_dt(lr.start_at)} a été"
                f" <strong>refusée</strong>.</p>"
                f"{'<p>Raison : ' + (lr.review_note or '') + '</p>' if lr.review_note else ''}"
                f"<p>N'hésite pas à en discuter avec ton responsable.</p>"
                f"</div>"
            ),
        )

    return await _to_read(db, lr)
