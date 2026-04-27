"""Follow-up CRUD + listing.

    GET    /api/v1/follow-ups?subject_type=prospect&subject_id=42
    POST   /api/v1/follow-ups
    PATCH  /api/v1/follow-ups/{id}
    DELETE /api/v1/follow-ups/{id}
    GET    /api/v1/follow-ups/overdue          → suivis dépassés
    GET    /api/v1/follow-ups/upcoming         → suivis à faire (today + tomorrow)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.follow_up import FollowUp
from app.services.follow_up import compute_next_after_log


router = APIRouter(prefix="/follow-ups", tags=["follow-ups"])


class FollowUpRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject_type: str
    subject_id: int
    kind: str
    direction: str
    outcome: str
    notes: Optional[str]
    performed_by_user_id: Optional[int]
    performed_at: datetime
    next_action_at: Optional[datetime]
    next_action_label: Optional[str]
    created_at: datetime


class FollowUpCreate(BaseModel):
    subject_type: str = Field(..., pattern="^(prospect|soumission)$")
    subject_id: int = Field(..., gt=0)
    kind: str = Field(
        default="call",
        pattern="^(call|email|sms|visite|note|auto)$",
    )
    direction: str = Field(default="outbound", pattern="^(outbound|inbound)$")
    outcome: str = Field(
        default="reached",
        pattern=(
            "^(reached|voicemail|no_answer|interested|not_interested|"
            "won|lost|pending|scheduled)$"
        ),
    )
    notes: Optional[str] = None
    # Si non fourni, on calcule via compute_next_after_log
    next_action_at: Optional[datetime] = None
    next_action_label: Optional[str] = None
    # Label de l'étape qu'on vient de compléter, sert au calcul du
    # next step quand next_action_at n'est pas fourni manuellement.
    completed_step: Optional[str] = None


class FollowUpUpdate(BaseModel):
    outcome: Optional[str] = Field(
        default=None,
        pattern=(
            "^(reached|voicemail|no_answer|interested|not_interested|"
            "won|lost|pending|scheduled)$"
        ),
    )
    notes: Optional[str] = None
    next_action_at: Optional[datetime] = None
    next_action_label: Optional[str] = None


@router.get("", response_model=List[FollowUpRead])
async def list_follow_ups(
    db: DBSession,
    _: CurrentUser,
    subject_type: Optional[str] = Query(default=None),
    subject_id: Optional[int] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> List[FollowUpRead]:
    stmt = select(FollowUp)
    if subject_type:
        stmt = stmt.where(FollowUp.subject_type == subject_type)
    if subject_id is not None:
        stmt = stmt.where(FollowUp.subject_id == subject_id)
    stmt = stmt.order_by(FollowUp.performed_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [FollowUpRead.model_validate(r) for r in rows]


@router.get("/overdue", response_model=List[FollowUpRead])
async def list_overdue(
    db: DBSession, _: RequireManager
) -> List[FollowUpRead]:
    """Suivis dont next_action_at est dans le passé et qui sont
    encore en attente (kind=auto + outcome=scheduled, ou outcome ∉
    STOP_OUTCOMES)."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(FollowUp)
        .where(
            FollowUp.next_action_at.is_not(None),
            FollowUp.next_action_at <= now,
            FollowUp.outcome.notin_(["won", "lost", "not_interested"]),
        )
        .order_by(FollowUp.next_action_at.asc())
        .limit(500)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [FollowUpRead.model_validate(r) for r in rows]


@router.get("/upcoming", response_model=List[FollowUpRead])
async def list_upcoming(
    db: DBSession,
    _: RequireManager,
    days: int = Query(default=7, ge=1, le=30),
) -> List[FollowUpRead]:
    """Suivis à faire dans les `days` prochains jours."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    stmt = (
        select(FollowUp)
        .where(
            FollowUp.next_action_at.is_not(None),
            FollowUp.next_action_at >= now,
            FollowUp.next_action_at <= end,
            FollowUp.outcome.notin_(["won", "lost", "not_interested"]),
        )
        .order_by(FollowUp.next_action_at.asc())
        .limit(500)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [FollowUpRead.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=FollowUpRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_follow_up(
    data: FollowUpCreate,
    db: DBSession,
    user: CurrentUser,
) -> FollowUpRead:
    next_at = data.next_action_at
    next_label = data.next_action_label
    if next_at is None and data.outcome not in ("won", "lost", "not_interested"):
        # Auto-calcul
        step = compute_next_after_log(
            subject_type=data.subject_type,
            last_label=data.completed_step,
            outcome=data.outcome,
        )
        if step:
            next_label, next_at = step

    fu = FollowUp(
        subject_type=data.subject_type,
        subject_id=data.subject_id,
        kind=data.kind,
        direction=data.direction,
        outcome=data.outcome,
        notes=(data.notes.strip() if data.notes else None),
        performed_by_user_id=user.id,
        next_action_at=next_at,
        next_action_label=next_label,
    )
    db.add(fu)
    await db.flush()
    await db.refresh(fu)
    return FollowUpRead.model_validate(fu)


@router.patch("/{fu_id}", response_model=FollowUpRead)
async def update_follow_up(
    fu_id: int,
    data: FollowUpUpdate,
    db: DBSession,
    _: CurrentUser,
) -> FollowUpRead:
    fu = (
        await db.execute(select(FollowUp).where(FollowUp.id == fu_id))
    ).scalar_one_or_none()
    if fu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suivi introuvable.")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(fu, field, value)
    await db.flush()
    await db.refresh(fu)
    return FollowUpRead.model_validate(fu)


@router.delete("/{fu_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_follow_up(
    fu_id: int, db: DBSession, _: RequireManager
) -> None:
    fu = (
        await db.execute(select(FollowUp).where(FollowUp.id == fu_id))
    ).scalar_one_or_none()
    if fu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suivi introuvable.")
    await db.delete(fu)
    await db.flush()


# ------------------------ Prospector queue ------------------------


class QueueItem(BaseModel):
    """Élément de la queue d'un prospecteur — un lead à rappeler/visiter
    avec sa prochaine action prévue, sa fenêtre (en retard / today /
    tomorrow / later) et un snapshot du contact (nom + tél + adresse)
    pour ne pas avoir à fetcher le contact séparément."""

    contact_request_id: int
    contact_name: str
    contact_phone: Optional[str]
    contact_email: Optional[str]
    contact_address: Optional[str]
    contact_status: str
    contact_assigned_to_user_id: Optional[int]
    last_follow_up: Optional[FollowUpRead]
    next_action_at: Optional[datetime]
    next_action_label: Optional[str]
    bucket: str  # overdue | today | tomorrow | later | none


class QueueOut(BaseModel):
    overdue: List[QueueItem]
    today: List[QueueItem]
    tomorrow: List[QueueItem]
    later: List[QueueItem]
    total: int


@router.get(
    "/queue",
    response_model=QueueOut,
    summary="Queue de prospection : leads avec prochaine action "
    "prévue, groupés par fenêtre temporelle. Tri principal = "
    "overdue first.",
)
async def get_queue(
    db: DBSession,
    current_user: CurrentUser,
    mine: bool = Query(
        default=False,
        description="Si true, ne retourne que les leads assignés au "
        "user courant.",
    ),
    days_ahead: int = Query(default=14, ge=1, le=60),
) -> QueueOut:
    """Construit la queue d'un prospecteur :
    1. Charge les contact_requests visibles (assignés au user si mine
       est true ; sinon tous les actifs).
    2. Pour chaque lead, récupère le DERNIER follow-up.
    3. Groupe par fenêtre temporelle selon next_action_at.

    Hyper performant : 2 queries SQL au total — pas de N+1.
    """
    from sqlalchemy import and_
    from app.models.contact_request import ContactRequest

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    after_tomorrow = tomorrow_start + timedelta(days=1)
    horizon = today_start + timedelta(days=days_ahead)

    # 1. Contact requests visibles
    cr_stmt = select(ContactRequest).where(
        ContactRequest.status.notin_(["lost", "spam", "won"])
    )
    if mine:
        cr_stmt = cr_stmt.where(
            ContactRequest.assigned_to_user_id == current_user.id
        )
    cr_stmt = cr_stmt.order_by(ContactRequest.created_at.desc()).limit(500)
    contacts = (await db.execute(cr_stmt)).scalars().all()
    if not contacts:
        return QueueOut(
            overdue=[], today=[], tomorrow=[], later=[], total=0
        )

    cr_ids = [c.id for c in contacts]

    # 2. Dernier follow-up par contact. On charge tous les FU des
    #    prospects en une query, puis on garde le plus récent par
    #    subject_id côté Python — simple et rapide pour <500 leads.
    fu_stmt = (
        select(FollowUp)
        .where(
            and_(
                FollowUp.subject_type == "prospect",
                FollowUp.subject_id.in_(cr_ids),
            )
        )
        .order_by(FollowUp.performed_at.desc())
    )
    all_fus = (await db.execute(fu_stmt)).scalars().all()
    last_fu_by_contact: dict[int, FollowUp] = {}
    for fu in all_fus:
        # La query est triée desc, donc le premier rencontré pour un
        # subject_id donné est le plus récent.
        if fu.subject_id not in last_fu_by_contact:
            last_fu_by_contact[fu.subject_id] = fu

    # 3. Grouping
    overdue: List[QueueItem] = []
    today: List[QueueItem] = []
    tomorrow: List[QueueItem] = []
    later: List[QueueItem] = []

    for c in contacts:
        last_fu = last_fu_by_contact.get(c.id)
        next_at = last_fu.next_action_at if last_fu else None
        next_label = last_fu.next_action_label if last_fu else None
        bucket = "none"
        if next_at:
            if next_at < today_start:
                bucket = "overdue"
            elif next_at < tomorrow_start:
                bucket = "today"
            elif next_at < after_tomorrow:
                bucket = "tomorrow"
            elif next_at < horizon:
                bucket = "later"
            else:
                bucket = "none"  # trop loin → ignore
        item = QueueItem(
            contact_request_id=c.id,
            contact_name=c.name,
            contact_phone=c.phone,
            contact_email=c.email,
            contact_address=c.address,
            contact_status=c.status,
            contact_assigned_to_user_id=c.assigned_to_user_id,
            last_follow_up=(
                FollowUpRead.model_validate(last_fu) if last_fu else None
            ),
            next_action_at=next_at,
            next_action_label=next_label,
            bucket=bucket,
        )
        if bucket == "overdue":
            overdue.append(item)
        elif bucket == "today":
            today.append(item)
        elif bucket == "tomorrow":
            tomorrow.append(item)
        elif bucket == "later":
            later.append(item)

    overdue.sort(key=lambda x: x.next_action_at or now)
    today.sort(key=lambda x: x.next_action_at or now)
    tomorrow.sort(key=lambda x: x.next_action_at or now)
    later.sort(key=lambda x: x.next_action_at or now)

    return QueueOut(
        overdue=overdue,
        today=today,
        tomorrow=tomorrow,
        later=later,
        total=len(overdue) + len(today) + len(tomorrow) + len(later),
    )


# ------------------------ CRM dashboard stats ------------------------


class ProspectorStats(BaseModel):
    user_id: int
    total_calls: int
    total_emails: int
    total_visits: int
    reached: int
    interested: int
    won: int
    lost: int
    avg_response_rate: float  # reached / outbound calls
    conversion_rate: float    # won / (won + lost)


class CrmDashboardOut(BaseModel):
    period_days: int
    total_leads: int
    new_leads: int
    by_status: dict
    avg_time_to_first_contact_hours: Optional[float]
    follow_ups_count: int
    overdue_count: int
    upcoming_count: int
    leads_per_week: List[dict]
    per_prospector: List[ProspectorStats]
    # SLA = nombre de leads dont le 1er contact n'a pas été fait
    # dans les `sla_first_contact_hours` heures.
    sla_breach_count: int = 0
    sla_threshold_hours: int = 4


@router.get(
    "/dashboard/crm",
    response_model=CrmDashboardOut,
    summary="Statistiques agrégées du CRM : volume, conversion, "
    "performance par prospecteur. Manager+ uniquement.",
)
async def crm_dashboard(
    db: DBSession,
    _: RequireManager,
    period_days: int = Query(default=90, ge=7, le=365),
) -> CrmDashboardOut:
    from sqlalchemy import and_
    from app.models.contact_request import ContactRequest

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=period_days)

    # Tous les leads dans la période + leur status
    cr_rows = (
        await db.execute(
            select(ContactRequest).where(
                ContactRequest.created_at >= period_start
            )
        )
    ).scalars().all()

    total_leads = len(cr_rows)
    by_status: dict = {}
    week_counts: dict = {}
    cr_ids: list[int] = []
    for r in cr_rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        cr_ids.append(r.id)
        if r.created_at:
            iso_year, iso_week, _ = r.created_at.isocalendar()
            wk = f"{iso_year}-W{iso_week:02d}"
            week_counts[wk] = week_counts.get(wk, 0) + 1
    new_leads = sum(
        1 for r in cr_rows if r.status == "new"
    )

    # Tous les follow-ups de ces leads
    fu_rows = []
    if cr_ids:
        fu_rows = (
            await db.execute(
                select(FollowUp).where(
                    and_(
                        FollowUp.subject_type == "prospect",
                        FollowUp.subject_id.in_(cr_ids),
                    )
                )
            )
        ).scalars().all()

    follow_ups_count = len(fu_rows)
    overdue_count = sum(
        1
        for f in fu_rows
        if f.next_action_at
        and f.next_action_at < now
        and f.outcome not in ("won", "lost", "not_interested")
    )
    upcoming_count = sum(
        1
        for f in fu_rows
        if f.next_action_at
        and f.next_action_at >= now
        and f.next_action_at <= now + timedelta(days=14)
        and f.outcome not in ("won", "lost", "not_interested")
    )

    # Time to first contact : pour chaque lead, premier follow-up
    # outbound. On agrège la moyenne.
    first_outbound_by_lead: dict[int, datetime] = {}
    for f in fu_rows:
        if f.direction != "outbound":
            continue
        prev = first_outbound_by_lead.get(f.subject_id)
        if prev is None or f.performed_at < prev:
            first_outbound_by_lead[f.subject_id] = f.performed_at
    cr_by_id = {r.id: r for r in cr_rows}
    deltas: list[float] = []
    for lead_id, first_at in first_outbound_by_lead.items():
        c = cr_by_id.get(lead_id)
        if c is None or c.created_at is None:
            continue
        delta_h = (first_at - c.created_at).total_seconds() / 3600.0
        if delta_h >= 0:
            deltas.append(delta_h)
    avg_time_to_first = (
        round(sum(deltas) / len(deltas), 2) if deltas else None
    )

    # Per-prospector stats : agrégat par performed_by_user_id
    per_user: dict[int, dict] = {}
    for f in fu_rows:
        uid = f.performed_by_user_id
        if uid is None:
            continue
        u = per_user.setdefault(
            uid,
            {
                "calls": 0,
                "emails": 0,
                "visits": 0,
                "outbound": 0,
                "reached": 0,
                "interested": 0,
                "won": 0,
                "lost": 0,
            },
        )
        if f.kind == "call":
            u["calls"] += 1
        elif f.kind == "email":
            u["emails"] += 1
        elif f.kind == "visite":
            u["visits"] += 1
        if f.direction == "outbound":
            u["outbound"] += 1
        if f.outcome == "reached":
            u["reached"] += 1
        elif f.outcome == "interested":
            u["interested"] += 1
        elif f.outcome == "won":
            u["won"] += 1
        elif f.outcome == "lost":
            u["lost"] += 1

    per_prospector: List[ProspectorStats] = []
    for uid, st in per_user.items():
        avg_resp = (
            st["reached"] / st["outbound"] if st["outbound"] else 0.0
        )
        finals = st["won"] + st["lost"]
        conv = st["won"] / finals if finals else 0.0
        per_prospector.append(
            ProspectorStats(
                user_id=uid,
                total_calls=st["calls"],
                total_emails=st["emails"],
                total_visits=st["visits"],
                reached=st["reached"],
                interested=st["interested"],
                won=st["won"],
                lost=st["lost"],
                avg_response_rate=round(avg_resp, 3),
                conversion_rate=round(conv, 3),
            )
        )
    # Tri : meilleur conv rate puis volume
    per_prospector.sort(
        key=lambda p: (p.conversion_rate, p.total_calls), reverse=True
    )

    leads_per_week = [
        {"week": k, "count": v}
        for k, v in sorted(week_counts.items())
    ][-26:]

    # SLA : combien de leads ont passé sla_hours sans aucun contact
    # manuel (call/email/sms/visite) ?
    from app.core.config import settings as _sla_settings
    sla_hours = max(1, int(getattr(_sla_settings, "sla_first_contact_hours", 4)))
    sla_cutoff = now - timedelta(hours=sla_hours)
    contacted_lead_ids: set[int] = set()
    for f in fu_rows:
        if f.kind in ("call", "email", "sms", "visite"):
            contacted_lead_ids.add(f.subject_id)
    sla_breach_count = sum(
        1
        for r in cr_rows
        if r.created_at
        and r.created_at < sla_cutoff
        and r.id not in contacted_lead_ids
        and r.status in ("new", "contacted", "qualified")
    )

    return CrmDashboardOut(
        period_days=period_days,
        total_leads=total_leads,
        new_leads=new_leads,
        by_status=by_status,
        avg_time_to_first_contact_hours=avg_time_to_first,
        follow_ups_count=follow_ups_count,
        overdue_count=overdue_count,
        upcoming_count=upcoming_count,
        leads_per_week=leads_per_week,
        per_prospector=per_prospector,
        sla_breach_count=sla_breach_count,
        sla_threshold_hours=sla_hours,
    )


# ------------------------ Daily route ------------------------


class DailyRouteIn(BaseModel):
    """Optimisation de la route du prospecteur pour la journée."""

    start_lat: Optional[float] = None
    start_lng: Optional[float] = None
    bucket: str = Field(
        default="today",
        pattern="^(overdue|today|tomorrow|all)$",
    )
    max_stops: int = Field(default=10, ge=2, le=12)


class DailyRouteOut(BaseModel):
    ordered_lead_ids: List[int]  # ContactRequest IDs
    skipped_no_address: int
    total_distance_m: Optional[float]
    total_duration_s: Optional[float]
    google_maps_url: Optional[str]
    notes: List[str]


@router.post(
    "/daily-route",
    response_model=DailyRouteOut,
    summary="Optimise l'ordre de visite des leads de ta queue (prospect "
    "address-géocodé) via OSRM. Ouvre Google Maps avec l'ordre optimal.",
)
async def daily_route(
    payload: DailyRouteIn,
    db: DBSession,
    current_user: CurrentUser,
) -> DailyRouteOut:
    """Reprend la même queue que /follow-ups/queue mais ne garde que
    les leads avec une adresse géolocalisable. Géocode chaque adresse
    via Nominatim (cache local pas implémenté — au pire 1 appel/lead),
    puis optimise via OSRM."""
    import httpx
    from app.integrations.nominatim import reverse_geocode  # noqa: F401
    from app.models.contact_request import ContactRequest

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    after_tomorrow = tomorrow_start + timedelta(days=1)

    cr_stmt = select(ContactRequest).where(
        ContactRequest.assigned_to_user_id == current_user.id,
        ContactRequest.status.notin_(["lost", "spam", "won"]),
    )
    contacts = (await db.execute(cr_stmt)).scalars().all()
    if not contacts:
        return DailyRouteOut(
            ordered_lead_ids=[],
            skipped_no_address=0,
            total_distance_m=None,
            total_duration_s=None,
            google_maps_url=None,
            notes=["Aucun lead assigné à toi."],
        )

    # Charge les FU pour bucketer
    cr_ids = [c.id for c in contacts]
    fus = (
        await db.execute(
            select(FollowUp).where(
                FollowUp.subject_type == "prospect",
                FollowUp.subject_id.in_(cr_ids),
            )
            .order_by(FollowUp.performed_at.desc())
        )
    ).scalars().all()
    last_fu: dict[int, FollowUp] = {}
    for f in fus:
        if f.subject_id not in last_fu:
            last_fu[f.subject_id] = f

    # Sélection selon le bucket demandé
    selected: list = []
    for c in contacts:
        f = last_fu.get(c.id)
        next_at = f.next_action_at if f else None
        keep = False
        if payload.bucket == "all":
            keep = True
        elif next_at is None:
            keep = payload.bucket == "today"  # nouveau lead = today
        elif next_at < today_start:
            keep = payload.bucket == "overdue"
        elif next_at < tomorrow_start:
            keep = payload.bucket == "today"
        elif next_at < after_tomorrow:
            keep = payload.bucket == "tomorrow"
        if keep:
            selected.append(c)

    # Filtre : doit avoir une adresse
    skipped = 0
    addressed: list = []
    for c in selected:
        if (c.address or "").strip():
            addressed.append(c)
        else:
            skipped += 1

    # Géocodage des adresses (séquentiel, max 1/sec policy Nominatim)
    coords: list[tuple[int, float, float]] = []
    geo_notes: list[str] = []
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=True
    ) as http:
        for c in addressed[: payload.max_stops]:
            full = ", ".join(
                x for x in (c.address, "Québec, Canada") if x
            )
            try:
                r = await http.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={
                        "q": full,
                        "format": "json",
                        "limit": "1",
                    },
                    headers={
                        "User-Agent": "h2.0-Horizon/1.0 (contact@immohorizon.com)",
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    if data:
                        coords.append(
                            (c.id, float(data[0]["lat"]), float(data[0]["lon"]))
                        )
                        continue
            except httpx.HTTPError:
                pass
            geo_notes.append(f"Pas géocodable : {c.name}")

    if len(coords) < 2:
        return DailyRouteOut(
            ordered_lead_ids=[c[0] for c in coords],
            skipped_no_address=skipped,
            total_distance_m=None,
            total_duration_s=None,
            google_maps_url=None,
            notes=[
                "Au moins 2 leads géocodables sont nécessaires pour "
                "optimiser une route."
            ]
            + geo_notes,
        )

    # OSRM trip
    osrm_coords: list[str] = []
    if payload.start_lat is not None and payload.start_lng is not None:
        osrm_coords.append(
            f"{payload.start_lng:.6f},{payload.start_lat:.6f}"
        )
    for _, lat, lng in coords:
        osrm_coords.append(f"{lng:.6f},{lat:.6f}")

    url = (
        "https://router.project-osrm.org/trip/v1/driving/"
        + ";".join(osrm_coords)
        + "?source=first&roundtrip=false&overview=false"
    )
    try:
        async with httpx.AsyncClient(
            timeout=20.0, follow_redirects=True
        ) as http:
            r = await http.get(
                url, headers={"User-Agent": "h2.0-Horizon/1.0"}
            )
            if r.status_code != 200:
                raise HTTPException(
                    502, f"OSRM HTTP {r.status_code}"
                )
            data = r.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            502, f"OSRM erreur réseau : {exc}"
        ) from exc

    if data.get("code") != "Ok":
        raise HTTPException(
            502, f"OSRM réponse invalide : {data.get('code')}"
        )

    waypoints = data.get("waypoints", [])
    has_start = (
        payload.start_lat is not None and payload.start_lng is not None
    )
    waypoint_to_lead = (
        [None] + [c[0] for c in coords]
        if has_start
        else [c[0] for c in coords]
    )
    indexed: list[tuple[int, int]] = []
    for orig_idx, wp in enumerate(waypoints):
        oi = wp.get("waypoint_index")
        if oi is None:
            continue
        lid = waypoint_to_lead[orig_idx]
        if lid is not None:
            indexed.append((oi, lid))
    indexed.sort()
    ordered_ids = [lid for _, lid in indexed]

    # URL Google Maps
    parts: list[str] = []
    if has_start:
        parts.append(f"{payload.start_lat:.6f},{payload.start_lng:.6f}")
    by_id = {cid: (lat, lng) for cid, lat, lng in coords}
    for cid in ordered_ids:
        lat, lng = by_id[cid]
        parts.append(f"{lat:.6f},{lng:.6f}")
    gm_url = "https://www.google.com/maps/dir/" + "/".join(parts)

    trip = data["trips"][0] if data.get("trips") else {}
    return DailyRouteOut(
        ordered_lead_ids=ordered_ids,
        skipped_no_address=skipped,
        total_distance_m=float(trip.get("distance", 0)) or None,
        total_duration_s=float(trip.get("duration", 0)) or None,
        google_maps_url=gm_url,
        notes=geo_notes,
    )
