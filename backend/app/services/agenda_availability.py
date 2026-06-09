"""Service de vérification de disponibilité d'un créneau agenda.

Combine plusieurs sources de conflits pour un user × période :
  1. AgendaEvent existant (overlap)
  2. ExternalBusyBlock (Outlook synchronisé)
  3. ProjectPhase auquel le user est assigné pendant ce slot
  4. Travel time depuis le RV précédent (si géocodable)
  5. Travel time vers le RV suivant (si géocodable)

Renvoie un objet structuré avec :
  - is_available : bool
  - conflicts   : list[str] — raisons en français lisible
  - travel_info : { from_prev_sec, to_next_sec } si calculé
  - suggestions : list de créneaux alternatifs (futur)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import openrouteservice
from app.integrations.nominatim import geocode_address as nominatim_geocode
from app.models.agenda_event import AgendaEvent
from app.models.calendar_sync import ExternalBusyBlock
from app.models.geocoded_address import GeocodedAddress
from app.models.employe import Employe
from app.models.project_assignees import ProjectPhaseAssignee
from app.models.project_phase import ProjectPhase
from app.models.user import User

log = logging.getLogger(__name__)


@dataclass
class SlotCheckResult:
    is_available: bool
    conflicts: List[str] = field(default_factory=list)
    travel_from_prev_sec: Optional[int] = None
    travel_to_next_sec: Optional[int] = None
    prev_event_id: Optional[int] = None
    next_event_id: Optional[int] = None


_WS_RE = re.compile(r"\s+")


def _normalize_address(addr: str) -> str:
    s = (addr or "").strip().lower()
    return _WS_RE.sub(" ", s)


async def geocode_with_cache(
    db: AsyncSession, address: str
) -> Optional[Tuple[float, float]]:
    """Géocode une adresse en passant par notre cache DB. Renvoie
    (lat, lng) ou None si impossible."""
    if not address or not address.strip():
        return None
    key = _normalize_address(address)
    cached = (
        await db.execute(
            select(GeocodedAddress).where(GeocodedAddress.address_key == key)
        )
    ).scalar_one_or_none()
    if cached is not None:
        return (float(cached.lat), float(cached.lng))
    # Pas en cache → Nominatim (gratuit, 1 req/sec — on est en mode
    # ponctuel donc OK).
    try:
        result = await nominatim_geocode(address)
    except Exception as exc:  # noqa: BLE001
        log.warning("Nominatim error for '%s': %s", address[:80], exc)
        return None
    if not result:
        return None
    lat = result.get("lat")
    lng = result.get("lng")
    if lat is None or lng is None:
        return None
    try:
        row = GeocodedAddress(
            address_key=key[:500],
            address_original=address[:500],
            lat=float(lat),
            lng=float(lng),
            provider="nominatim",
        )
        db.add(row)
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not cache geocode for '%s': %s", address[:80], exc)
    return (float(lat), float(lng))


async def travel_time_between(
    db: AsyncSession, addr_a: str, addr_b: str
) -> Optional[int]:
    """Calcule le temps de trajet entre 2 adresses. Géocode chacune,
    puis OpenRouteService Matrix. Fallback heuristique haversine si
    OpenRouteService n'est pas configuré."""
    coords_a = await geocode_with_cache(db, addr_a)
    coords_b = await geocode_with_cache(db, addr_b)
    if not coords_a or not coords_b:
        return None
    secs = await openrouteservice.travel_time_seconds(coords_a, coords_b)
    if secs is not None:
        return secs
    # Fallback heuristique
    return openrouteservice.haversine_fallback_seconds(coords_a, coords_b)


async def check_slot_availability(
    db: AsyncSession,
    *,
    user_id: int,
    start_at: datetime,
    end_at: datetime,
    location: Optional[str] = None,
    prep_buffer_min: int = 0,
    exclude_event_id: Optional[int] = None,
) -> SlotCheckResult:
    """Vérifie si un user peut prendre un RV à ce créneau.

    Args:
        user_id : assignee du RV
        start_at / end_at : créneau du RV (UTC)
        location : adresse du RV (sert au calcul de transit)
        prep_buffer_min : minutes de prép à réserver AVANT le RV
        exclude_event_id : si on est en train d'éditer un event,
            l'exclure du check (sinon il se chevauche lui-même).
    """
    result = SlotCheckResult(is_available=True)
    effective_start = start_at - timedelta(minutes=prep_buffer_min or 0)

    # 1. AgendaEvent overlap (même user)
    overlap_stmt = select(AgendaEvent).where(
        AgendaEvent.assignee_user_id == user_id,
        AgendaEvent.start_at < end_at,
        or_(
            AgendaEvent.end_at.is_(None),
            AgendaEvent.end_at > effective_start,
        ),
    )
    if exclude_event_id is not None:
        overlap_stmt = overlap_stmt.where(
            AgendaEvent.id != exclude_event_id
        )
    overlapping = (await db.execute(overlap_stmt)).scalars().all()
    if overlapping:
        for ev in overlapping:
            result.conflicts.append(
                f"Conflit avec « {ev.title} » "
                f"({ev.start_at.strftime('%H:%M')}–"
                f"{(ev.end_at or ev.start_at).strftime('%H:%M')})"
            )
        result.is_available = False

    # 2. ExternalBusyBlock (Outlook ICS synchronisé)
    ext_overlap = (
        await db.execute(
            select(ExternalBusyBlock).where(
                ExternalBusyBlock.user_id == user_id,
                ExternalBusyBlock.start_at < end_at,
                ExternalBusyBlock.end_at > effective_start,
            )
        )
    ).scalars().all()
    if ext_overlap:
        result.conflicts.append(
            f"Bloqué dans l'agenda Outlook synchronisé ({len(ext_overlap)} bloc(s))"
        )
        result.is_available = False

    # 3. ProjectPhase auquel ce user est assigné pendant ce slot.
    #    Le pont User → Employe se fait par email (un Employe est
    #    relié à un User via son email). ProjectPhase a start_date +
    #    duration_days (pas d'end_date stocké) — on calcule end_date
    #    en Python.
    user_email = (
        await db.execute(select(User.email).where(User.id == user_id))
    ).scalar_one_or_none()
    if user_email:
        slot_date_start = effective_start.date()
        slot_date_end = end_at.date()
        # Récupère toutes les phases assignées au user (via N-M ou
        # via assignee_employe_id direct sur ProjectPhase). On filtre
        # ensuite par date_range en Python (compute end_date).
        user_employes = (
            await db.execute(
                select(Employe.id).where(Employe.email == user_email)
            )
        ).scalars().all()
        phase_ids: set[int] = set()
        if user_employes:
            mn_rows = (
                await db.execute(
                    select(ProjectPhaseAssignee.phase_id).where(
                        ProjectPhaseAssignee.employe_id.in_(user_employes)
                    )
                )
            ).scalars().all()
            phase_ids.update(mn_rows)
            direct_rows = (
                await db.execute(
                    select(ProjectPhase.id).where(
                        ProjectPhase.assignee_employe_id.in_(user_employes)
                    )
                )
            ).scalars().all()
            phase_ids.update(direct_rows)
        conflicting_labels: list[str] = []
        if phase_ids:
            phases = (
                await db.execute(
                    select(ProjectPhase).where(
                        ProjectPhase.id.in_(phase_ids),
                        ProjectPhase.start_date.is_not(None),
                    )
                )
            ).scalars().all()
            # On affiche l'ADRESSE du projet (et non le nom de phase qui
            # peut être périmé, ex. « projet 121 » saisi à la création du
            # devis puis renommé) pour que le message de conflit soit clair.
            proj_ids = {
                getattr(p, "project_id", None)
                for p in phases
                if getattr(p, "project_id", None)
            }
            projects_by_id: dict = {}
            if proj_ids:
                from app.models.project import Project as _Proj

                projects_by_id = {
                    pr.id: pr
                    for pr in (
                        await db.execute(
                            select(_Proj).where(_Proj.id.in_(proj_ids))
                        )
                    ).scalars().all()
                }
            for p in phases:
                if p.start_date is None:
                    continue
                duration = int(p.duration_days or 0)
                p_end = p.start_date + timedelta(days=max(duration - 1, 0))
                if p.start_date <= slot_date_end and p_end >= slot_date_start:
                    proj = projects_by_id.get(getattr(p, "project_id", None))
                    label = ""
                    if proj is not None:
                        label = (proj.address or "").strip() or (
                            proj.name or ""
                        )
                    if not label:
                        label = p.name or f"phase #{p.id}"
                    conflicting_labels.append(label)
        if conflicting_labels:
            # Dédup en gardant l'ordre.
            uniq = list(dict.fromkeys(conflicting_labels))
            result.conflicts.append(
                "Déjà assigné(e) à un chantier en cours : "
                f"{', '.join(uniq)}"
            )
            result.is_available = False

    # 4 + 5. Transit time depuis l'event précédent et vers le suivant.
    #         Seulement si on a une location pour ce RV ET pour le
    #         précédent/suivant.
    if location and location.strip():
        # Event précédent du user le même jour
        prev_event = (
            await db.execute(
                select(AgendaEvent)
                .where(
                    AgendaEvent.assignee_user_id == user_id,
                    AgendaEvent.end_at.is_not(None),
                    AgendaEvent.end_at <= effective_start,
                    AgendaEvent.location.is_not(None),
                    AgendaEvent.id != (exclude_event_id or -1),
                )
                .order_by(AgendaEvent.end_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if prev_event and prev_event.location:
            secs = await travel_time_between(
                db, prev_event.location, location
            )
            if secs is not None:
                result.travel_from_prev_sec = secs
                result.prev_event_id = prev_event.id
                gap_sec = (
                    effective_start - prev_event.end_at  # type: ignore[operator]
                ).total_seconds()
                if gap_sec < secs:
                    needed_min = int((secs - gap_sec) / 60) + 1
                    result.conflicts.append(
                        f"⚠️ Transit insuffisant depuis « {prev_event.title} » "
                        f"({int(secs/60)} min de route, il manque ~{needed_min} min)"
                    )
                    result.is_available = False

        # Event suivant du user le même jour
        next_event = (
            await db.execute(
                select(AgendaEvent)
                .where(
                    AgendaEvent.assignee_user_id == user_id,
                    AgendaEvent.start_at >= end_at,
                    AgendaEvent.location.is_not(None),
                    AgendaEvent.id != (exclude_event_id or -1),
                )
                .order_by(AgendaEvent.start_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if next_event and next_event.location:
            secs = await travel_time_between(
                db, location, next_event.location
            )
            if secs is not None:
                result.travel_to_next_sec = secs
                result.next_event_id = next_event.id
                gap_sec = (
                    next_event.start_at - end_at
                ).total_seconds()
                if gap_sec < secs:
                    needed_min = int((secs - gap_sec) / 60) + 1
                    result.conflicts.append(
                        f"⚠️ Transit insuffisant vers « {next_event.title} » "
                        f"({int(secs/60)} min de route, il manque ~{needed_min} min)"
                    )
                    result.is_available = False

    return result
