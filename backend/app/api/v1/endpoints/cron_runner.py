"""HTTP triggers for scheduled jobs — alternative gratuite aux
Render Cron Jobs (payants). On expose les jobs via des endpoints
protégés par un secret partagé, qu'on peut hit depuis GitHub Actions
ou cron-job.org sur le schedule de notre choix.

Les endpoints utilisent un X-Cron-Secret header (ou ?secret= en query
string en fallback) qui doit matcher l'env var CRON_SECRET. Sans
secret valide, on retourne 401 sans révéler la cible.

    POST /api/v1/cron/run/unassigned-day-alerts
    POST /api/v1/cron/run/follow-up-reminders
    POST /api/v1/cron/run/facture-reminders
    POST /api/v1/cron/run/seo-daily

Chaque endpoint relance la fonction `_run()` du job correspondant.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel

from app.core.config import settings


log = logging.getLogger(__name__)

router = APIRouter(prefix="/cron", tags=["cron"])


class CronResult(BaseModel):
    ok: bool
    job: str


def _check_secret(
    header_secret: Optional[str], query_secret: Optional[str]
) -> None:
    if not settings.cron_secret:
        # Si pas configuré côté serveur, on refuse tout pour éviter
        # une exécution non protégée.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "CRON_SECRET non configuré sur le serveur.",
        )
    provided = header_secret or query_secret
    if not provided or provided != settings.cron_secret:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid cron secret."
        )


@router.post("/run/unassigned-day-alerts", response_model=CronResult)
async def trigger_unassigned_day_alerts(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> CronResult:
    _check_secret(x_cron_secret, secret)
    from app.jobs.unassigned_day_alerts import _run

    try:
        await _run()
    except Exception as exc:
        log.exception("Cron unassigned_day_alerts failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return CronResult(ok=True, job="unassigned-day-alerts")


@router.post("/run/follow-up-reminders", response_model=CronResult)
async def trigger_follow_up_reminders(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> CronResult:
    _check_secret(x_cron_secret, secret)
    from app.jobs.follow_up_reminders import _run

    try:
        await _run()
    except Exception as exc:
        log.exception("Cron follow_up_reminders failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return CronResult(ok=True, job="follow-up-reminders")


@router.post("/run/facture-reminders", response_model=CronResult)
async def trigger_facture_reminders(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> CronResult:
    _check_secret(x_cron_secret, secret)
    from app.jobs.facture_reminders import run as _job_run

    try:
        await _job_run()
    except Exception as exc:
        log.exception("Cron facture_reminders failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return CronResult(ok=True, job="facture-reminders")


@router.post("/run/appointment-reminders", response_model=CronResult)
async def trigger_appointment_reminders(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> CronResult:
    _check_secret(x_cron_secret, secret)
    from app.jobs.appointment_reminders import run as _job_run

    try:
        await _job_run()
    except Exception as exc:
        log.exception("Cron appointment_reminders failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return CronResult(ok=True, job="appointment-reminders")


class QGDailyPulseResult(CronResult):
    """Détail des entreprises traitées par le cron Daily Pulse."""

    total: int = 0
    generated: int = 0
    skipped: int = 0
    errors: int = 0


class QGInsightsResult(CronResult):
    total: int = 0
    created: int = 0
    errors: int = 0


@router.api_route(
    "/run/qg-weekly-insights",
    methods=["GET", "POST"],
    response_model=QGInsightsResult,
)
async def trigger_qg_weekly_insights(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
    force: bool = Query(default=False),
) -> QGInsightsResult:
    """Cron hebdo : génère des insights pour toutes les entreprises
    actives. À planifier 1×/semaine (lundi 8h)."""
    _check_secret(x_cron_secret, secret)
    from app.db.session import AsyncSessionLocal
    from app.services.qg_insights import generate_for_all_active

    try:
        async with AsyncSessionLocal() as db:
            result = await generate_for_all_active(db, force=force)
            await db.commit()
    except Exception as exc:
        log.exception("Cron qg_weekly_insights failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return QGInsightsResult(
        ok=True,
        job="qg-weekly-insights",
        total=result.get("total", 0),
        created=result.get("created", 0),
        errors=result.get("errors", 0),
    )


@router.api_route(
    "/run/qg-daily-pulse",
    methods=["GET", "POST"],
    response_model=QGDailyPulseResult,
)
async def trigger_qg_daily_pulse(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
    force: bool = Query(default=False),
) -> QGDailyPulseResult:
    """Cron quotidien : génère le briefing IA pour toutes les
    entreprises actives. À planifier ~7h heure locale via cron-job.org
    ou GitHub Actions. ``force=true`` regénère les briefings du jour."""
    _check_secret(x_cron_secret, secret)
    from app.db.session import AsyncSessionLocal
    from app.services.qg_daily_pulse import generate_for_all_active

    try:
        async with AsyncSessionLocal() as db:
            result = await generate_for_all_active(db, force=force)
            await db.commit()
    except Exception as exc:
        log.exception("Cron qg_daily_pulse failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return QGDailyPulseResult(
        ok=True,
        job="qg-daily-pulse",
        total=result.get("total", 0),
        generated=result.get("generated", 0),
        skipped=result.get("skipped", 0),
        errors=result.get("errors", 0),
    )


class QGRecurrenceResult(BaseModel):
    ok: bool
    job: str
    templates_scanned: int = 0
    taches_created: int = 0
    templates_updated: int = 0
    errors: int = 0


@router.api_route(
    "/run/qg-tache-recurrence",
    methods=["GET", "POST"],
    response_model=QGRecurrenceResult,
)
async def trigger_qg_tache_recurrence(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> QGRecurrenceResult:
    """Cron quotidien : matérialise les tâches récurrentes dues du jour.

    À planifier ~6h heure locale via cron-job.org. Idempotent —
    n'écrira pas en double pour le même (template, due_date).
    """
    _check_secret(x_cron_secret, secret)
    from app.db.session import AsyncSessionLocal
    from app.services.qg_recurrence import materialize_due_templates

    try:
        async with AsyncSessionLocal() as db:
            result = await materialize_due_templates(db)
    except Exception as exc:
        log.exception("Cron qg_tache_recurrence failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return QGRecurrenceResult(
        ok=True,
        job="qg-tache-recurrence",
        templates_scanned=result.get("templates_scanned", 0),
        taches_created=result.get("taches_created", 0),
        templates_updated=result.get("templates_updated", 0),
        errors=len(result.get("errors", [])),
    )


class BailRenouvellementCronResult(BaseModel):
    ok: bool
    job: str
    bails_scanned: int = 0
    avis_crees: int = 0
    courriels_envoyes: int = 0
    skipped: int = 0
    errors: int = 0


@router.api_route(
    "/run/bail-renouvellements",
    methods=["GET", "POST"],
    response_model=BailRenouvellementCronResult,
)
async def trigger_bail_renouvellements(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> BailRenouvellementCronResult:
    """Cron quotidien : génère et envoie les avis de modification du bail
    pour les baux dont l'échéance tombe dans 4-6 mois. Idempotent.
    À planifier ~7h via cron-job.org."""
    _check_secret(x_cron_secret, secret)
    from app.db.session import AsyncSessionLocal
    from app.services.bail_renouvellement import (
        scan_and_send_due_renouvellements,
    )

    try:
        async with AsyncSessionLocal() as db:
            res = await scan_and_send_due_renouvellements(db)
    except Exception as exc:
        log.exception("Cron bail_renouvellements failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return BailRenouvellementCronResult(
        ok=True,
        job="bail-renouvellements",
        bails_scanned=res.bails_scanned,
        avis_crees=res.avis_crees,
        courriels_envoyes=res.courriels_envoyes,
        skipped=res.skipped,
        errors=len(res.errors or []),
    )


class CalendarSyncCronResult(BaseModel):
    ok: bool
    job: str
    feeds_total: int = 0
    feeds_synced: int = 0
    feeds_failed: int = 0


@router.api_route(
    "/run/calendar-feeds-sync",
    methods=["GET", "POST"],
    response_model=CalendarSyncCronResult,
)
async def trigger_calendar_feeds_sync(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> CalendarSyncCronResult:
    """Cron horaire : resynchronise tous les flux ICS de tous les users.

    À planifier toutes les heures via cron-job.org. Idempotent —
    `sync_user_feed` remplace les ExternalBusyBlock existants par lot.
    """
    _check_secret(x_cron_secret, secret)
    from app.db.session import AsyncSessionLocal
    from app.models.calendar_sync import UserCalendarFeed
    from app.services.ical_sync import sync_user_feed
    from sqlalchemy import select

    total = 0
    synced = 0
    failed = 0
    try:
        async with AsyncSessionLocal() as db:
            feeds = (
                await db.execute(select(UserCalendarFeed))
            ).scalars().all()
            total = len(feeds)
            for f in feeds:
                try:
                    await sync_user_feed(db, f)
                    synced += 1
                except Exception:
                    log.exception("sync feed %s failed", f.id)
                    failed += 1
            await db.commit()
    except Exception as exc:
        log.exception("Cron calendar_feeds_sync failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return CalendarSyncCronResult(
        ok=True,
        job="calendar-feeds-sync",
        feeds_total=total,
        feeds_synced=synced,
        feeds_failed=failed,
    )


class BailRenewTasksResult(BaseModel):
    ok: bool
    job: str
    bails_scanned: int = 0
    tasks_created: int = 0
    tasks_skipped: int = 0
    errors: int = 0


@router.api_route(
    "/run/bail-renouvellement-tasks",
    methods=["GET", "POST"],
    response_model=BailRenewTasksResult,
)
async def trigger_bail_renouvellement_tasks(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> BailRenewTasksResult:
    """Cron daily : crée les tâches QG « préparer le renouvellement »
    pour les baux dont la fenêtre de rappel est ouverte (5 mois avant
    la fin pour bail ≥ 12 mois, 2 mois sinon). Idempotent (tag
    `bail-renew:{bail_id}` empêche les doublons)."""
    _check_secret(x_cron_secret, secret)
    from app.db.session import AsyncSessionLocal
    from app.services.bail_renew_tasks import scan_and_create_renew_tasks

    try:
        async with AsyncSessionLocal() as db:
            res = await scan_and_create_renew_tasks(db)
    except Exception as exc:
        log.exception("Cron bail_renew_tasks failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return BailRenewTasksResult(
        ok=True,
        job="bail-renouvellement-tasks",
        bails_scanned=res.get("bails_scanned", 0),
        tasks_created=res.get("tasks_created", 0),
        tasks_skipped=res.get("tasks_skipped", 0),
        errors=len(res.get("errors", []) or []),
    )
