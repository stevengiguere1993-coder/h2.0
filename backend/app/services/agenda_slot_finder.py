"""Slot finder — trouve les créneaux libres pour un user (closer,
chargé de projet, etc.) en respectant tous les filtres :
- pas de conflit AgendaEvent
- pas de bloc Outlook
- pas assigné à une phase de chantier ce jour-là
- transit OK depuis/vers les RV adjacents
- dans les heures d'ouverture (par défaut 8h-17h lun-ven)

Utilisé par /api/v1/agenda/suggest-slots et par Léa au téléphone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment_type import AppointmentType
from app.models.user import User
from app.models.user_business_role import UserBusinessRole
from app.services.agenda_availability import check_slot_availability

log = logging.getLogger(__name__)


# Heures d'ouverture par défaut (à rendre configurable par user en
# vague 5). Pour l'instant : lun-ven 8h-17h, en heure locale Montréal.
BUSINESS_DAYS = {0, 1, 2, 3, 4}  # lundi=0
BUSINESS_START_HOUR = 8
BUSINESS_END_HOUR = 17

# Pas de recherche de créneau : 30 min. On essaie chaque demi-heure
# dans la plage horaire, jusqu'à trouver `max_results` slots dispos.
SLOT_STEP_MIN = 30


@dataclass
class SuggestedSlot:
    user_id: int
    user_email: str
    user_display: str
    start_at: datetime
    end_at: datetime
    appointment_type_id: int
    travel_from_prev_sec: Optional[int] = None
    travel_to_next_sec: Optional[int] = None


def _is_business_hour(dt: datetime) -> bool:
    if dt.weekday() not in BUSINESS_DAYS:
        return False
    return BUSINESS_START_HOUR <= dt.hour < BUSINESS_END_HOUR


async def _candidate_users(
    db: AsyncSession,
    role_kind: Optional[str],
    user_id: Optional[int],
) -> List[User]:
    if user_id is not None:
        u = (
            await db.execute(
                select(User).where(
                    User.id == user_id, User.is_active.is_(True)
                )
            )
        ).scalar_one_or_none()
        return [u] if u else []
    if not role_kind:
        return []
    rows = (
        await db.execute(
            select(User)
            .join(UserBusinessRole, UserBusinessRole.user_id == User.id)
            .where(
                UserBusinessRole.role_kind == role_kind,
                User.is_active.is_(True),
            )
        )
    ).scalars().unique().all()
    return list(rows)


def _user_display(u: User) -> str:
    fn = (u.first_name or "").strip()
    ln = (u.last_name or "").strip()
    if fn or ln:
        return f"{fn} {ln}".strip()
    return u.email


async def find_available_slots(
    db: AsyncSession,
    *,
    appointment_type_id: int,
    location: Optional[str],
    role_kind: Optional[str] = None,
    user_id: Optional[int] = None,
    earliest_start: Optional[datetime] = None,
    days_ahead: int = 7,
    max_results: int = 3,
) -> List[SuggestedSlot]:
    """Cherche les meilleurs créneaux disponibles.

    Args:
        appointment_type_id : type de RV (détermine durée + buffer prép)
        location            : adresse du RV (pour calcul transit)
        role_kind           : rôle requis (ex. "closer") — peut être None
        user_id             : OU user_id explicite (prioritaire sur role)
        earliest_start      : ne propose rien avant cette date (par
                              défaut : maintenant + 24h, en heure pleine)
        days_ahead          : profondeur de recherche en jours
        max_results         : nombre de créneaux retournés
    """
    apt_type = (
        await db.execute(
            select(AppointmentType).where(
                AppointmentType.id == appointment_type_id,
                AppointmentType.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if apt_type is None:
        return []

    candidates = await _candidate_users(db, role_kind, user_id)
    if not candidates:
        return []

    duration = timedelta(minutes=apt_type.default_duration_min)
    prep_buffer = apt_type.prep_buffer_min or 0

    if earliest_start is None:
        now = datetime.now(timezone.utc)
        earliest_start = (now + timedelta(hours=24)).replace(
            minute=0, second=0, microsecond=0
        )

    end_window = earliest_start + timedelta(days=days_ahead)

    found: List[SuggestedSlot] = []
    for user in candidates:
        cursor = earliest_start
        while cursor < end_window and len(found) < max_results * len(candidates):
            if not _is_business_hour(cursor):
                cursor += timedelta(minutes=SLOT_STEP_MIN)
                continue
            slot_end = cursor + duration
            # Le slot doit aussi finir dans les heures ouvrables
            if (
                slot_end.weekday() not in BUSINESS_DAYS
                or slot_end.hour > BUSINESS_END_HOUR
                or (slot_end.hour == BUSINESS_END_HOUR and slot_end.minute > 0)
            ):
                # Saute au prochain matin
                next_morning = (cursor + timedelta(days=1)).replace(
                    hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0
                )
                cursor = next_morning
                continue

            check = await check_slot_availability(
                db,
                user_id=user.id,
                start_at=cursor,
                end_at=slot_end,
                location=location,
                prep_buffer_min=prep_buffer,
            )
            if check.is_available:
                found.append(
                    SuggestedSlot(
                        user_id=user.id,
                        user_email=user.email,
                        user_display=_user_display(user),
                        start_at=cursor,
                        end_at=slot_end,
                        appointment_type_id=apt_type.id,
                        travel_from_prev_sec=check.travel_from_prev_sec,
                        travel_to_next_sec=check.travel_to_next_sec,
                    )
                )
                # Pour éviter de proposer N créneaux le même jour, on
                # saute au lendemain matin une fois qu'on a trouvé un
                # slot pour ce user ce jour-là.
                next_morning = (cursor + timedelta(days=1)).replace(
                    hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0
                )
                cursor = next_morning
            else:
                cursor += timedelta(minutes=SLOT_STEP_MIN)

    # Trie par date croissante (le prospect veut généralement le plus tôt)
    found.sort(key=lambda s: s.start_at)
    return found[:max_results]
