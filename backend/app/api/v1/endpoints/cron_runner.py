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


@router.post("/run/teams-meeting-sync", response_model=CronResult)
async def trigger_teams_meeting_sync(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> CronResult:
    """Importe les rencontres Teams transcrites en fiches Rencontres."""
    _check_secret(x_cron_secret, secret)
    from app.jobs.teams_meeting_sync import _run

    try:
        await _run()
    except Exception as exc:
        log.exception("Cron teams_meeting_sync failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return CronResult(ok=True, job="teams-meeting-sync")


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
    force: bool = Query(default=False),
) -> CronResult:
    _check_secret(x_cron_secret, secret)
    from app.db.session import AsyncSessionLocal
    from app.jobs.facture_reminders import run as _job_run
    from app.services.cron_guard import claim_cron_run

    # Anti-doublon : pas deux fois en moins de 2 h (sauf force).
    if not force:
        async with AsyncSessionLocal() as gdb:
            if not await claim_cron_run(gdb, "facture-reminders", 2 * 3600):
                return CronResult(ok=True, job="facture-reminders")

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


@router.post("/run/email-inbound", response_model=CronResult)
async def trigger_email_inbound(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> CronResult:
    """Relève les courriels entrants et les rattache aux fiches CRM
    (nécessite Graph Mail.Read)."""
    _check_secret(x_cron_secret, secret)
    from app.db.session import AsyncSessionLocal
    from app.services.email_inbound import poll_inbound_emails

    try:
        async with AsyncSessionLocal() as db:
            await poll_inbound_emails(db)
            await db.commit()
    except Exception as exc:
        log.exception("Cron email_inbound failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return CronResult(ok=True, job="email-inbound")


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
    # Respecte le toggle « Synchro calendriers iCal » du hub
    # d'automatisations. is_automation_enabled est fail-open (True si
    # la ligne/table est absente) → défaut ON = comportement inchangé.
    from app.services.automation_state import is_automation_enabled

    if not await is_automation_enabled("ical_sync_all"):
        return CalendarSyncCronResult(ok=True, job="calendar-feeds-sync")

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


class DevlogWeeklyReportResult(CronResult):
    """Résultat du cron hebdo : récap d'envois aux clients."""
    projects_total: int = 0
    emails_sent: int = 0
    skipped_no_activity: int = 0
    skipped_no_client_email: int = 0


@router.api_route(
    "/run/devlog-weekly-client-reports",
    methods=["GET", "POST"],
    response_model=DevlogWeeklyReportResult,
)
async def trigger_devlog_weekly_client_reports(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> DevlogWeeklyReportResult:
    """Cron hebdo : rapport d'activité par projet devlog aux clients.

    À planifier vendredi 16h heure Montréal via cron-job.org (cron
    ``0 21 * * 5`` en UTC ≈ vendredi 16h-17h EDT/EST selon DST).
    Skip silencieusement les projets sans activité dans la semaine."""
    _check_secret(x_cron_secret, secret)
    from app.db.session import AsyncSessionLocal
    from app.jobs.devlog_weekly_client_report import run_weekly_client_reports

    try:
        async with AsyncSessionLocal() as db:
            res = await run_weekly_client_reports(db)
    except Exception as exc:
        log.exception("Cron devlog_weekly_client_reports failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return DevlogWeeklyReportResult(
        ok=True,
        job="devlog-weekly-client-reports",
        projects_total=res.get("projects_total", 0),
        emails_sent=res.get("emails_sent", 0),
        skipped_no_activity=res.get("skipped_no_activity", 0),
        skipped_no_client_email=res.get("skipped_no_client_email", 0),
    )


class DevlogNpsDispatchResult(CronResult):
    """Résultat du cron NPS : projets éligibles + envois effectifs."""
    eligible_projects: int = 0
    dispatched: int = 0
    skipped_no_client_email: int = 0


@router.api_route(
    "/run/devlog-nps-dispatch",
    methods=["GET", "POST"],
    response_model=DevlogNpsDispatchResult,
)
async def trigger_devlog_nps_dispatch(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> DevlogNpsDispatchResult:
    """Cron quotidien : envoi du formulaire NPS 7j après livraison.

    À planifier ~10h heure locale via cron-job.org. Idempotent —
    n'envoie pas deux fois pour le même projet (table
    ``devlog_nps_responses`` sert d'état)."""
    _check_secret(x_cron_secret, secret)
    from app.db.session import AsyncSessionLocal
    from app.jobs.devlog_nps_dispatch import run_nps_dispatch

    try:
        async with AsyncSessionLocal() as db:
            res = await run_nps_dispatch(db)
    except Exception as exc:
        log.exception("Cron devlog_nps_dispatch failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Job a échoué : {exc}",
        )
    return DevlogNpsDispatchResult(
        ok=True,
        job="devlog-nps-dispatch",
        eligible_projects=res.get("eligible_projects", 0),
        dispatched=res.get("dispatched", 0),
        skipped_no_client_email=res.get("skipped_no_client_email", 0),
    )


# ─── Mega-cron : exécute tous les jobs daily en un seul appel ──────────


class MegaCronResult(BaseModel):
    """Résultat agrégé du mega-cron : statut par sous-job."""
    ok: bool
    job: str = "all-daily"
    jobs_run: int = 0
    jobs_ok: int = 0
    jobs_failed: int = 0
    details: dict = {}


async def _safe(name: str, coro_factory, results: dict) -> None:
    """Exécute coro_factory(); enregistre le résultat sous results[name]."""
    try:
        out = await coro_factory()
        results[name] = {"ok": True, "result": out if out is not None else "ran"}
    except Exception as exc:  # noqa: BLE001
        log.exception("Mega-cron sub-job %s failed: %s", name, exc)
        results[name] = {"ok": False, "error": str(exc)[:240]}


@router.api_route(
    "/run/all-daily",
    methods=["GET", "POST"],
    response_model=MegaCronResult,
)
async def trigger_all_daily(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
    force: bool = Query(default=False),
) -> MegaCronResult:
    """Mega-cron daily : exécute tous les jobs schedulés du jour
    en séquence dans un seul appel HTTP. À configurer une seule fois
    dans cron-job.org (~6h heure locale) — toute nouvelle routine ajoutée
    par la suite sera automatiquement incluse sans toucher à cron-job.

    Gère les erreurs job par job — si l'un échoue, les suivants
    s'exécutent quand même et le rapport agrégé remonte les détails.

    Anti-doublon : refuse de tourner si un run a déjà eu lieu il y a moins
    de 6 h (sauf ``force=true``), pour éviter les doubles courriels de
    rappel si le scheduler rejoue l'appel.
    """
    _check_secret(x_cron_secret, secret)
    from app.db.session import AsyncSessionLocal
    from app.services.cron_guard import claim_cron_run

    if not force:
        async with AsyncSessionLocal() as gdb:
            claimed = await claim_cron_run(gdb, "all-daily", 6 * 3600)
        if not claimed:
            return MegaCronResult(
                ok=True,
                job="all-daily",
                jobs_run=0,
                jobs_ok=0,
                jobs_failed=0,
                details={"skipped": "run trop récent (< 6 h) — anti-doublon"},
            )

    details: dict = {}

    # Jobs construction / prospection (legacy, sans DB session paramétrée)
    from app.jobs.unassigned_day_alerts import _run as run_unassigned
    from app.jobs.follow_up_reminders import _run as run_follow_ups
    from app.jobs.facture_reminders import run as run_facture
    from app.jobs.appointment_reminders import run as run_appointment

    await _safe("unassigned-day-alerts", run_unassigned, details)
    await _safe("follow-up-reminders", run_follow_ups, details)
    await _safe("facture-reminders", run_facture, details)
    await _safe("appointment-reminders", run_appointment, details)

    # Jobs QG / immobilier (utilisent une session DB managée)
    async def _run_qg_daily_pulse():
        from app.services.qg_daily_pulse import generate_for_all_active

        async with AsyncSessionLocal() as db:
            r = await generate_for_all_active(db, force=False)
            await db.commit()
            return r

    async def _run_qg_recurrence():
        from app.services.qg_recurrence import materialize_due_templates

        async with AsyncSessionLocal() as db:
            r = await materialize_due_templates(db)
            await db.commit()
            return r

    async def _run_bail_renew_tasks():
        from app.services.bail_renew_tasks import scan_and_create_renew_tasks

        async with AsyncSessionLocal() as db:
            r = await scan_and_create_renew_tasks(db)
            await db.commit()
            return r

    await _safe("qg-daily-pulse", _run_qg_daily_pulse, details)
    await _safe("qg-tache-recurrence", _run_qg_recurrence, details)
    await _safe("bail-renouvellement-tasks", _run_bail_renew_tasks, details)

    async def _run_email_inbound():
        from app.services.email_inbound import poll_inbound_emails

        async with AsyncSessionLocal() as db:
            r = await poll_inbound_emails(db)
            await db.commit()
            return r

    await _safe("email-inbound", _run_email_inbound, details)

    # Import QB→Kratos des factures (reliées à un projet). Inerte tant
    # que l'interrupteur `qbo_auto_sync` est OFF (fail-closed).
    async def _run_qbo_invoice_pull():
        from app.services.qbo_auto_sync import is_qbo_auto_sync_enabled

        if not await is_qbo_auto_sync_enabled():
            return {"skipped": "qbo_auto_sync_off"}
        from app.services.qbo_invoice_pull import pull_invoices_from_qbo

        async with AsyncSessionLocal() as db:
            r = await pull_invoices_from_qbo(db, dry_run=False)
            await db.commit()
            return r

    await _safe("qbo-invoice-pull", _run_qbo_invoice_pull, details)

    # Import QB→Kratos des coûts projet (Bills + Purchases). Inerte si
    # l'interrupteur qbo_auto_sync est OFF.
    async def _run_qbo_cost_pull():
        from app.services.qbo_auto_sync import is_qbo_auto_sync_enabled

        if not await is_qbo_auto_sync_enabled():
            return {"skipped": "qbo_auto_sync_off"}
        from app.services.qbo_cost_pull import pull_project_costs_from_qbo

        async with AsyncSessionLocal() as db:
            r = await pull_project_costs_from_qbo(db, dry_run=False)
            await db.commit()
            return r

    await _safe("qbo-cost-pull", _run_qbo_cost_pull, details)

    # Insights weekly : on tente quand même daily, le service est
    # idempotent et skip si rien à faire.
    async def _run_qg_insights():
        from app.services.qg_insights import generate_for_all_active

        async with AsyncSessionLocal() as db:
            r = await generate_for_all_active(db)
            await db.commit()
            return r

    await _safe("qg-weekly-insights", _run_qg_insights, details)

    # NPS post-livraison (envoi 7j après status='livre'). Daily idempotent.
    async def _run_devlog_nps_dispatch():
        from app.jobs.devlog_nps_dispatch import run_nps_dispatch

        async with AsyncSessionLocal() as db:
            r = await run_nps_dispatch(db)
            return r

    await _safe("devlog-nps-dispatch", _run_devlog_nps_dispatch, details)

    ok_count = sum(1 for v in details.values() if v.get("ok"))
    fail_count = sum(1 for v in details.values() if not v.get("ok"))
    return MegaCronResult(
        ok=fail_count == 0,
        job="all-daily",
        jobs_run=len(details),
        jobs_ok=ok_count,
        jobs_failed=fail_count,
        details=details,
    )


@router.api_route(
    "/run/all-hourly",
    methods=["GET", "POST"],
    response_model=MegaCronResult,
)
async def trigger_all_hourly(
    x_cron_secret: Optional[str] = Header(default=None),
    secret: Optional[str] = Query(default=None),
) -> MegaCronResult:
    """Mega-cron horaire : jobs à fréquence > 1× par jour (sync calendrier
    ICS). À configurer une seule fois dans cron-job.org si tu veux les
    busy blocks à jour pour les suggestions intelligentes d'assignation."""
    _check_secret(x_cron_secret, secret)
    from app.db.session import AsyncSessionLocal

    details: dict = {}

    async def _run_calendar_sync():
        # Respecte le toggle « Synchro calendriers iCal » du hub
        # d'automatisations. is_automation_enabled est fail-open (True si
        # la ligne/table est absente), donc le comportement par défaut
        # (toggle ON) est strictement identique à avant.
        from app.services.automation_state import is_automation_enabled

        if not await is_automation_enabled("ical_sync_all"):
            return {"skipped": True, "feeds_total": 0, "synced": 0, "failed": 0}

        from app.models.calendar_sync import UserCalendarFeed
        from app.services.ical_sync import sync_user_feed
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            feeds = (await db.execute(select(UserCalendarFeed))).scalars().all()
            ok = 0
            fail = 0
            for f in feeds:
                try:
                    await sync_user_feed(db, f)
                    ok += 1
                except Exception:
                    fail += 1
            await db.commit()
            return {"feeds_total": len(feeds), "synced": ok, "failed": fail}

    await _safe("calendar-feeds-sync", _run_calendar_sync, details)

    # Déduplication des achats — TOUJOURS (pas de gating QB) : c'est une
    # opération purement DB qui collapse les doublons (même réf + montant,
    # même transaction QB). Indispensable car le pull QB qui la déclenchait
    # est inerte quand l'auto-sync est OFF → sinon les doublons restent.
    async def _run_achat_dedupe():
        from app.services.achat_dedupe import dedupe_achats

        async with AsyncSessionLocal() as db:
            n = await dedupe_achats(db)
            await db.commit()
            return {"deduped": n}

    await _safe("achat-dedupe", _run_achat_dedupe, details)

    async def _run_facture_dedupe():
        from app.services.facture_dedupe import dedupe_factures

        async with AsyncSessionLocal() as db:
            n = await dedupe_factures(db)
            await db.commit()
            return {"deduped": n}

    await _safe("facture-dedupe", _run_facture_dedupe, details)

    # Automatisme « à refacturer » : toute dépense d'un projet à CONTRAT /
    # ESTIMÉ doit afficher « À refacturer » (is_billable=True) tant qu'elle
    # n'est pas refacturée. Purement DB (aucun appel QB), donc NON gardé par
    # l'interrupteur d'auto-sync. Idempotent.
    async def _run_achat_billable_correct():
        from app.services.achat_billable_correct import (
            correct_billable_for_contract_projects,
        )

        async with AsyncSessionLocal() as db:
            n = await correct_billable_for_contract_projects(db)
            return {"corrected": n}

    await _safe(
        "achat-billable-correct", _run_achat_billable_correct, details
    )

    # Import QB → Kratos (factures + coûts projet) à l'heure, pour une
    # synchro quasi temps réel. Inerte tant que l'interrupteur
    # `qbo_auto_sync` est OFF (fail-closed). Idempotent (clé = ID QBO).
    async def _run_qbo_invoice_pull_hourly():
        from app.services.qbo_auto_sync import is_qbo_auto_sync_enabled

        if not await is_qbo_auto_sync_enabled():
            return {"skipped": "qbo_auto_sync_off"}
        from app.services.qbo_invoice_pull import pull_invoices_from_qbo

        async with AsyncSessionLocal() as db:
            r = await pull_invoices_from_qbo(db, dry_run=False)
            await db.commit()
            return r

    async def _run_qbo_cost_pull_hourly():
        from app.services.qbo_auto_sync import is_qbo_auto_sync_enabled

        if not await is_qbo_auto_sync_enabled():
            return {"skipped": "qbo_auto_sync_off"}
        from app.services.qbo_cost_pull import pull_project_costs_from_qbo

        async with AsyncSessionLocal() as db:
            r = await pull_project_costs_from_qbo(db, dry_run=False)
            await db.commit()
            return r

    await _safe("qbo-invoice-pull", _run_qbo_invoice_pull_hourly, details)
    await _safe("qbo-cost-pull", _run_qbo_cost_pull_hourly, details)

    # Filet : pousse vers QB les achats d'un projet PAS encore synchronisés
    # (créés/devenus payés sans que l'auto-push immédiat n'aboutisse). Gardé
    # par l'interrupteur d'auto-sync. Idempotent : sync_achat_to_qbo a sa
    # propre garde anti-doublon ; on ne prend que les achats sans lien QB.
    async def _run_qbo_achat_autopush_hourly():
        from app.services.qbo_auto_sync import is_qbo_auto_sync_enabled

        if not await is_qbo_auto_sync_enabled():
            return {"skipped": "qbo_auto_sync_off"}
        from sqlalchemy import select
        from app.models.achat import Achat
        from app.services.achat_qbo import sync_achat_to_qbo

        from datetime import datetime, timedelta, timezone

        recent_cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        async with AsyncSessionLocal() as db:
            ids = [
                int(r[0])
                for r in (
                    await db.execute(
                        select(Achat.id).where(
                            # Tout achat de PROJET, ou tout achat RÉCENT
                            # même sans projet (l'auto-push immédiat a pu
                            # échouer en silence). La fenêtre 14 j évite
                            # de migrer en masse le legacy sans projet.
                            (
                                Achat.project_id.is_not(None)
                                | (Achat.created_at >= recent_cutoff)
                            ),
                            Achat.status.in_(("received", "paid")),
                            Achat.qbo_bill_id.is_(None),
                            Achat.qbo_purchase_id.is_(None),
                        )
                    )
                ).all()
            ]
        pushed = 0
        failed = 0
        for aid in ids:
            try:
                async with AsyncSessionLocal() as s:
                    await sync_achat_to_qbo(s, aid)
                    await s.commit()
                pushed += 1
            except Exception:  # noqa: BLE001
                failed += 1
        return {"candidates": len(ids), "pushed": pushed, "failed": failed}

    await _safe("qbo-achat-autopush", _run_qbo_achat_autopush_hourly, details)

    # Filet : pousse vers QB les FACTURES CLIENTS émises (envoyées /
    # payées / en retard) qui n'ont pas encore de miroir Invoice QB —
    # l'auto-push à l'envoi est best-effort et SILENCIEUX, donc un échec
    # ponctuel (réseau, taxe, résolution du projet…) laissait la facture
    # absente de QB sans que personne ne le voie (ex. facture 117). Gardé
    # par l'interrupteur d'auto-sync ; idempotent (qbo_invoice_id).
    async def _run_qbo_facture_autopush_hourly():
        from app.services.qbo_auto_sync import is_qbo_auto_sync_enabled

        if not await is_qbo_auto_sync_enabled():
            return {"skipped": "qbo_auto_sync_off"}
        from sqlalchemy import select
        from app.models.facture import Facture
        from app.services.facture_qbo import sync_facture_to_qbo

        async with AsyncSessionLocal() as db:
            ids = [
                int(r[0])
                for r in (
                    await db.execute(
                        select(Facture.id).where(
                            Facture.status.in_(("sent", "paid", "overdue")),
                            Facture.qbo_invoice_id.is_(None),
                            Facture.client_id.is_not(None),
                        )
                    )
                ).all()
            ]
        pushed = 0
        failed = 0
        errors: dict[str, str] = {}
        for fid in ids:
            try:
                async with AsyncSessionLocal() as s:
                    await sync_facture_to_qbo(s, fid)
                    await s.commit()
                pushed += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                # Garde la raison des 5 premiers échecs pour diagnostic
                # (visible dans le résultat du cron / les logs).
                if len(errors) < 5:
                    errors[str(fid)] = str(exc)[:200]
        out = {"candidates": len(ids), "pushed": pushed, "failed": failed}
        if errors:
            out["errors"] = errors
        return out

    await _safe(
        "qbo-facture-autopush", _run_qbo_facture_autopush_hourly, details
    )

    ok_count = sum(1 for v in details.values() if v.get("ok"))
    fail_count = sum(1 for v in details.values() if not v.get("ok"))
    return MegaCronResult(
        ok=fail_count == 0,
        job="all-hourly",
        jobs_run=len(details),
        jobs_ok=ok_count,
        jobs_failed=fail_count,
        details=details,
    )
