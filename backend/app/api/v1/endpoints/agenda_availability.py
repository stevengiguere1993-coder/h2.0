"""Endpoints de disponibilité agenda — anti-collision + travel time.

  POST /api/v1/agenda/check-slot
       body : { user_id, start_at, end_at, location?, prep_buffer_min?,
                exclude_event_id? }
       returns : SlotCheckResult { is_available, conflicts[], travel_… }

  POST /api/v1/agenda/travel-time
       body : { from_address, to_address }
       returns : { seconds, minutes, provider }
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DBSession
from app.services.agenda_availability import (
    check_slot_availability,
    travel_time_between,
)
from app.integrations import openrouteservice


router = APIRouter(prefix="/agenda", tags=["agenda-availability"])


class SlotCheckRequest(BaseModel):
    user_id: int
    start_at: datetime
    end_at: datetime
    location: Optional[str] = Field(default=None, max_length=500)
    prep_buffer_min: int = Field(default=0, ge=0, le=240)
    exclude_event_id: Optional[int] = None


class SlotCheckResponse(BaseModel):
    is_available: bool
    conflicts: List[str]
    travel_from_prev_sec: Optional[int] = None
    travel_to_next_sec: Optional[int] = None
    prev_event_id: Optional[int] = None
    next_event_id: Optional[int] = None


@router.post(
    "/check-slot",
    response_model=SlotCheckResponse,
    summary="Vérifie si un user peut prendre un RV à un créneau donné",
)
async def check_slot(
    payload: SlotCheckRequest, _: CurrentUser, db: DBSession
) -> SlotCheckResponse:
    if payload.end_at <= payload.start_at:
        raise HTTPException(
            status_code=400, detail="end_at doit être après start_at"
        )
    r = await check_slot_availability(
        db,
        user_id=payload.user_id,
        start_at=payload.start_at,
        end_at=payload.end_at,
        location=payload.location,
        prep_buffer_min=payload.prep_buffer_min,
        exclude_event_id=payload.exclude_event_id,
    )
    return SlotCheckResponse(
        is_available=r.is_available,
        conflicts=r.conflicts,
        travel_from_prev_sec=r.travel_from_prev_sec,
        travel_to_next_sec=r.travel_to_next_sec,
        prev_event_id=r.prev_event_id,
        next_event_id=r.next_event_id,
    )


class TravelTimeRequest(BaseModel):
    from_address: str = Field(..., min_length=3, max_length=500)
    to_address: str = Field(..., min_length=3, max_length=500)


class TravelTimeResponse(BaseModel):
    seconds: Optional[int]
    minutes: Optional[int]
    provider: str
    is_openrouteservice_configured: bool


@router.post(
    "/travel-time",
    response_model=TravelTimeResponse,
    summary="Calcule le temps de trajet entre 2 adresses",
)
async def travel_time(
    payload: TravelTimeRequest, _: CurrentUser, db: DBSession
) -> TravelTimeResponse:
    secs = await travel_time_between(
        db, payload.from_address, payload.to_address
    )
    return TravelTimeResponse(
        seconds=secs,
        minutes=int(secs / 60) if secs is not None else None,
        provider="openrouteservice" if openrouteservice.is_configured() else "haversine_fallback",
        is_openrouteservice_configured=openrouteservice.is_configured(),
    )
