"""Schedule a prospect appointment — creates an AgendaEvent linked to
a ContactRequest and sends a confirmation email. The 24h reminder is
handled by the `appointment_reminders` cron.

    POST /api/v1/appointments   — schedule + notify
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import DBSession, RequireManager
from app.models.agenda_event import AgendaEvent
from app.models.contact_request import ContactRequest
from app.services.appointment_mail import send_appointment_confirmation


router = APIRouter(prefix="/appointments", tags=["appointments"])


class AppointmentCreate(BaseModel):
    contact_request_id: int
    title: str = Field(..., min_length=1, max_length=255)
    start_at: datetime
    end_at: datetime
    location: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    event_type: str = Field(default="visite", max_length=32)


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    start_at: datetime
    end_at: Optional[datetime]
    contact_request_id: Optional[int]
    assignee_id: Optional[int]
    event_type: str
    confirmation_sent_at: Optional[datetime] = None


@router.post(
    "",
    response_model=AppointmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def schedule_appointment(
    data: AppointmentCreate,
    db: DBSession,
    user: RequireManager,
    bg: BackgroundTasks,
) -> AppointmentRead:
    if data.end_at <= data.start_at:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Plage horaire invalide."
        )
    prospect = (
        await db.execute(
            select(ContactRequest).where(
                ContactRequest.id == data.contact_request_id
            )
        )
    ).scalar_one_or_none()
    if prospect is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Prospect introuvable."
        )

    event = AgendaEvent(
        title=data.title.strip(),
        description=(data.description or None),
        location=(data.location or None),
        start_at=data.start_at,
        end_at=data.end_at,
        all_day=False,
        assignee_id=data.assignee_id,
        contact_request_id=data.contact_request_id,
        event_type=data.event_type,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)

    # Fire the confirmation email in the background. Worst case the
    # send fails — the agenda event is still created and the cron will
    # try the 24h reminder as a fallback.
    async def _send_and_mark(
        prospect_id: int, event_id: int
    ) -> None:
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as fresh_db:
            pr = (
                await fresh_db.execute(
                    select(ContactRequest).where(
                        ContactRequest.id == prospect_id
                    )
                )
            ).scalar_one_or_none()
            ev = (
                await fresh_db.execute(
                    select(AgendaEvent).where(AgendaEvent.id == event_id)
                )
            ).scalar_one_or_none()
            if pr is None or ev is None:
                return
            ok = await send_appointment_confirmation(pr, ev)
            if ok:
                ev.confirmation_sent_at = datetime.now(timezone.utc)
                await fresh_db.commit()

    bg.add_task(_send_and_mark, prospect.id, event.id)

    return AppointmentRead.model_validate(event)
