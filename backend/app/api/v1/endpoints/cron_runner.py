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


@router.post("/run/qg-weekly-insights", response_model=QGInsightsResult)
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


@router.post("/run/qg-daily-pulse", response_model=QGDailyPulseResult)
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
