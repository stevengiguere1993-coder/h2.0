"""Change the status of a soumission and propagate to the linked prospect.

PATCH /api/v1/soumissions/{soumission_id}/status
Body: { "status": "accepted" | "rejected" | "expired" | "draft" | "sent" }

Propagation rules (only when the prospect isn't already in a terminal
state):
    soumission.sent     -> prospect.quoted
    soumission.accepted -> prospect.won
    soumission.rejected -> prospect.lost
    soumission.expired  -> prospect.lost
"""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.contact_request import ContactRequest, ContactRequestStatus
from app.models.soumission import Soumission, SoumissionStatus
from app.schemas.business import SoumissionRead


router = APIRouter(prefix="/soumissions", tags=["soumission-status"])


SoumissionStatusLiteral = Literal[
    "draft", "sent", "accepted", "rejected", "expired"
]


class StatusChangeRequest(BaseModel):
    status: SoumissionStatusLiteral


_SOUMISSION_TO_CRM = {
    SoumissionStatus.SENT.value: ContactRequestStatus.QUOTED.value,
    SoumissionStatus.ACCEPTED.value: ContactRequestStatus.WON.value,
    SoumissionStatus.REJECTED.value: ContactRequestStatus.LOST.value,
    SoumissionStatus.EXPIRED.value: ContactRequestStatus.LOST.value,
}


@router.patch(
    "/{soumission_id}/status",
    response_model=SoumissionRead,
    summary="Change soumission status and propagate to the prospect CRM",
)
async def change_soumission_status(
    soumission_id: int,
    data: StatusChangeRequest,
    db: DBSession,
    _: CurrentUser,
) -> SoumissionRead:
    sm = (
        await db.execute(select(Soumission).where(Soumission.id == soumission_id))
    ).scalar_one_or_none()
    if sm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Soumission not found")

    now = datetime.now(timezone.utc)
    sm.status = data.status
    if data.status == SoumissionStatus.SENT.value and sm.sent_at is None:
        sm.sent_at = now
    if data.status == SoumissionStatus.ACCEPTED.value and sm.accepted_at is None:
        sm.accepted_at = now

    target = _SOUMISSION_TO_CRM.get(data.status)
    if target and sm.contact_request_id:
        cr = (
            await db.execute(
                select(ContactRequest).where(
                    ContactRequest.id == sm.contact_request_id
                )
            )
        ).scalar_one_or_none()
        if cr is not None:
            # Terminal states are sticky: don't bump "won" back to
            # "quoted" just because we re-send later.
            if target == ContactRequestStatus.LOST.value and cr.status == ContactRequestStatus.WON.value:
                pass
            elif (
                target == ContactRequestStatus.QUOTED.value
                and cr.status
                in (
                    ContactRequestStatus.WON.value,
                    ContactRequestStatus.LOST.value,
                )
            ):
                pass
            else:
                cr.status = target

    await db.flush()
    await db.refresh(sm)
    return SoumissionRead.model_validate(sm)
