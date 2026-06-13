"""Cron hebdomadaire : rapport d'activité client par projet devlog.

Tous les vendredis 16h (heure Montréal — Eastern Time, fuseau du
business). Pour chaque ``DevlogProject`` au statut ``en_cours`` qui a eu
au moins une activité dans la semaine, on envoie un récap email au
client : heures saisies, phases avancées, factures envoyées/payées.

Pas d'activité = pas d'email (anti-spam). Aucun stockage d'état entre
exécutions : la fenêtre est calculée fraîchement à chaque run (du lundi
00h00 ET au vendredi 16h00 ET inclus).

Usage (HTTP trigger, cf. ``api/v1/endpoints/cron_runner.py``) :
    POST /api/v1/cron/run/devlog-weekly-client-reports

Pattern calqué sur ``app.jobs.devlog_facture_reminders``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.integrations.email_graph import get_mailer
from app.models.audit_log import AuditLog
from app.models.devlog_client import DevlogClient
from app.models.devlog_invoice import DevlogInvoice
from app.models.devlog_project import DevlogProject
from app.models.devlog_project_phase import DevlogProjectPhase
from app.models.devlog_time_entry import DevlogTimeEntry
from app.services.audit import log_action


log = logging.getLogger(__name__)

# Fuseau horaire du business (Montréal / Eastern Time). En mai 2026 on
# est en EDT (UTC-4). En hiver, EST (UTC-5). On utilise un offset fixe
# UTC-5 comme baseline et on documente le décalage estival : la précision
# d'1h sur l'heure d'envoi du rapport (15h vs 16h EDT) est acceptable
# pour un email hebdo. Pour faire mieux il faudrait ``zoneinfo`` mais on
# évite d'introduire une nouvelle dépendance ici.
_MONTREAL_OFFSET_HOURS = -5
_MONTREAL_TZ = timezone(timedelta(hours=_MONTREAL_OFFSET_HOURS))


def _fmt_money(n: float) -> str:
    """Format canadien : « 1 234,56 $ »."""
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} $"


def _fmt_hours(h: float) -> str:
    try:
        v = float(h or 0)
    except (TypeError, ValueError):
        v = 0.0
    s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} h"


def _week_window(now_utc: datetime) -> tuple[datetime, datetime]:
    """Retourne la fenêtre [lundi 00h00 Montréal ; vendredi 16h00
    Montréal] (en UTC) qui contient ou précède ``now_utc``.

    Si le cron tourne vendredi 16h (ou plus tard) → fenêtre de cette
    semaine. Si on le déclenche manuellement plus tard dans le weekend,
    on récupère quand même la semaine qui vient de s'écouler.
    """
    local = now_utc.astimezone(_MONTREAL_TZ)
    # weekday() : lundi=0, dimanche=6.
    monday_local_date = (local - timedelta(days=local.weekday())).date()
    monday_local = datetime.combine(
        monday_local_date, time(0, 0), tzinfo=_MONTREAL_TZ
    )
    friday_local = datetime.combine(
        monday_local_date + timedelta(days=4), time(16, 0), tzinfo=_MONTREAL_TZ
    )
    return (monday_local.astimezone(timezone.utc), friday_local.astimezone(timezone.utc))


async def _project_hours_this_week(
    db: AsyncSession, project_id: int, start_utc: datetime, end_utc: datetime
) -> float:
    """Total des heures saisies sur le projet entre start et end (sur la
    base de ``work_date`` — c'est la date « travail réel » du jour de
    saisie, comparée à la portion date de la fenêtre)."""
    start_date = start_utc.astimezone(_MONTREAL_TZ).date()
    end_date = end_utc.astimezone(_MONTREAL_TZ).date()
    total = (
        await db.execute(
            select(func.coalesce(func.sum(DevlogTimeEntry.hours), 0)).where(
                and_(
                    DevlogTimeEntry.project_id == project_id,
                    DevlogTimeEntry.work_date >= start_date,
                    DevlogTimeEntry.work_date <= end_date,
                )
            )
        )
    ).scalar_one()
    return float(total or 0)


async def _phase_changes_this_week(
    db: AsyncSession, project_id: int, start_utc: datetime, end_utc: datetime
) -> list[dict]:
    """Récupère les phases du projet qui ont eu un changement de status
    cette semaine (depuis ``audit_logs`` filtré sur les phases du projet
    + fenêtre temporelle). Retourne une liste de ``{name, new_status}``
    triée par horodatage."""
    phases = list(
        (
            await db.execute(
                select(DevlogProjectPhase).where(
                    DevlogProjectPhase.project_id == project_id
                )
            )
        ).scalars().all()
    )
    if not phases:
        return []
    by_id = {p.id: p for p in phases}
    rows = list(
        (
            await db.execute(
                select(AuditLog).where(
                    and_(
                        AuditLog.entity_type == "devlog_project_phase",
                        AuditLog.entity_id.in_(list(by_id.keys())),
                        AuditLog.created_at >= start_utc,
                        AuditLog.created_at <= end_utc,
                    )
                ).order_by(AuditLog.created_at.asc())
            )
        ).scalars().all()
    )
    out: list[dict] = []
    for row in rows:
        details = {}
        if row.details_json:
            try:
                details = json.loads(row.details_json)
            except Exception:
                details = {}
        # On filtre : seulement les events qui touchent au status. On
        # accepte 2 patterns : details = {"status": "x"} (set explicit)
        # ou {"changes": {"status": {...}}} (audit verbose).
        new_status = (
            details.get("new_status")
            or details.get("status")
            or (details.get("changes", {}) or {}).get("status", {}).get("to")
        )
        if not new_status:
            continue
        phase = by_id.get(row.entity_id) if row.entity_id else None
        if phase is None:
            continue
        out.append({"name": phase.name, "new_status": str(new_status)})
    # Dédoublonne : si une phase a eu plusieurs transitions, on garde la
    # dernière (la plus représentative).
    seen: dict[str, dict] = {}
    for entry in out:
        seen[entry["name"]] = entry
    return list(seen.values())


async def _invoices_window(
    db: AsyncSession,
    project_id: int,
    field: str,
    start_utc: datetime,
    end_utc: datetime,
) -> list[DevlogInvoice]:
    col = getattr(DevlogInvoice, field)
    return list(
        (
            await db.execute(
                select(DevlogInvoice).where(
                    and_(
                        DevlogInvoice.project_id == project_id,
                        col.isnot(None),
                        col >= start_utc,
                        col <= end_utc,
                    )
                ).order_by(col.asc())
            )
        ).scalars().all()
    )


def _build_email_html(
    project: DevlogProject,
    client_name: Optional[str],
    hours: float,
    phase_changes: list[dict],
    invoices_sent: list[DevlogInvoice],
    invoices_paid: list[DevlogInvoice],
    monday_local: datetime,
    friday_local: datetime,
) -> str:
    salutation = f"Bonjour {client_name}," if client_name else "Bonjour,"

    # Format date FR sans dépendance externe.
    def _fr_date(d: datetime) -> str:
        mois = [
            "janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre", "décembre",
        ]
        return f"{d.day} {mois[d.month - 1]}"

    week_range = f"du {_fr_date(monday_local)} au {_fr_date(friday_local)}"

    blocks: list[str] = []
    blocks.append(
        f"""
<p style="margin:0 0 16px 0">{salutation}</p>
<p style="margin:0 0 16px 0">
  Voici un récapitulatif de la semaine ({week_range}) pour votre projet
  <strong>{project.name}</strong>.
</p>
"""
    )

    # Cette semaine en bref
    bref_items = []
    if hours > 0:
        bref_items.append(f"<li>{_fmt_hours(hours)} de travail saisies</li>")
    if phase_changes:
        bref_items.append(
            f"<li>{len(phase_changes)} phase(s) avec un nouveau statut</li>"
        )
    if invoices_sent:
        bref_items.append(f"<li>{len(invoices_sent)} facture(s) envoyée(s)</li>")
    if invoices_paid:
        bref_items.append(f"<li>{len(invoices_paid)} facture(s) payée(s) — merci !</li>")
    if bref_items:
        blocks.append(
            "<h3 style=\"margin:20px 0 8px 0;color:#1e40af\">Cette semaine en bref</h3>"
            "<ul style=\"margin:0 0 16px 20px;padding:0\">"
            + "".join(bref_items)
            + "</ul>"
        )

    # Heures travaillées
    if hours > 0:
        blocks.append(
            "<h3 style=\"margin:20px 0 8px 0;color:#1e40af\">Heures travaillées</h3>"
            f"<p style=\"margin:0 0 16px 0\">Total de la semaine : "
            f"<strong>{_fmt_hours(hours)}</strong>.</p>"
        )

    # Avancement (phases)
    if phase_changes:
        items = "".join(
            f"<li><strong>{p['name']}</strong> → {p['new_status']}</li>"
            for p in phase_changes
        )
        blocks.append(
            "<h3 style=\"margin:20px 0 8px 0;color:#1e40af\">Avancement</h3>"
            f"<ul style=\"margin:0 0 16px 20px;padding:0\">{items}</ul>"
        )

    # Facturation
    if invoices_sent or invoices_paid:
        fac_blocks = []
        if invoices_sent:
            li = "".join(
                f"<li>Facture {inv.number or f'#{inv.id}'} — "
                f"{_fmt_money(inv.amount or 0)}</li>"
                for inv in invoices_sent
            )
            fac_blocks.append(
                "<p style=\"margin:8px 0 4px 0\"><strong>Envoyées cette semaine :</strong></p>"
                f"<ul style=\"margin:0 0 12px 20px;padding:0\">{li}</ul>"
            )
        if invoices_paid:
            li = "".join(
                f"<li>Facture {inv.number or f'#{inv.id}'} — "
                f"{_fmt_money(inv.amount or 0)}</li>"
                for inv in invoices_paid
            )
            fac_blocks.append(
                "<p style=\"margin:8px 0 4px 0\"><strong>Payées cette semaine :</strong></p>"
                f"<ul style=\"margin:0 0 12px 20px;padding:0\">{li}</ul>"
            )
        blocks.append(
            "<h3 style=\"margin:20px 0 8px 0;color:#1e40af\">Facturation</h3>"
            + "".join(fac_blocks)
        )

    blocks.append(
        """
<p style="margin:24px 0 4px 0;color:#555;font-size:12px">
  Cordialement,<br/>
  L'équipe Horizon &middot; Pôle Développement logiciel<br/>
  immohorizon.com
</p>
"""
    )

    return (
        '<div style="font-family:Helvetica,Arial,sans-serif;color:#111;'
        'line-height:1.55;max-width:620px">'
        + "".join(blocks)
        + "</div>"
    )


async def _load_client(
    db: AsyncSession, client_id: Optional[int]
) -> Optional[DevlogClient]:
    if client_id is None:
        return None
    return (
        await db.execute(
            select(DevlogClient).where(DevlogClient.id == client_id)
        )
    ).scalar_one_or_none()


async def run_weekly_client_reports(db: AsyncSession) -> dict:
    """Parcourt les projets en cours et envoie le rapport hebdo.

    Retourne un résumé ``{projects_total, emails_sent, skipped_no_activity,
    skipped_no_client_email}``.
    """
    from app.services.automation_state import is_automation_enabled
    if not await is_automation_enabled("devlog_weekly_client_report"):
        return {"skipped": "disabled"}
    mailer = get_mailer()
    now_utc = datetime.now(timezone.utc)
    start_utc, end_utc = _week_window(now_utc)
    monday_local = start_utc.astimezone(_MONTREAL_TZ)
    friday_local = end_utc.astimezone(_MONTREAL_TZ)

    projects = list(
        (
            await db.execute(
                select(DevlogProject).where(DevlogProject.status == "en_cours")
            )
        ).scalars().all()
    )

    emails_sent = 0
    skipped_no_activity = 0
    skipped_no_client_email = 0

    for project in projects:
        hours = await _project_hours_this_week(db, project.id, start_utc, end_utc)
        phase_changes = await _phase_changes_this_week(
            db, project.id, start_utc, end_utc
        )
        invoices_sent = await _invoices_window(
            db, project.id, "sent_at", start_utc, end_utc
        )
        invoices_paid = await _invoices_window(
            db, project.id, "paid_at", start_utc, end_utc
        )

        has_activity = bool(
            hours > 0 or phase_changes or invoices_sent or invoices_paid
        )
        if not has_activity:
            skipped_no_activity += 1
            continue

        client = await _load_client(db, project.client_id)
        to_email = (client.email or "").strip() if client is not None else ""
        if not to_email:
            skipped_no_client_email += 1
            continue

        if not mailer.ready:
            log.warning("Mailer non configuré — arrêt du job weekly reports.")
            break

        subject = f"Récap de la semaine — {project.name}"
        body = _build_email_html(
            project=project,
            client_name=client.name if client is not None else None,
            hours=hours,
            phase_changes=phase_changes,
            invoices_sent=invoices_sent,
            invoices_paid=invoices_paid,
            monday_local=monday_local,
            friday_local=friday_local,
        )

        try:
            await mailer.send(
                to=[to_email],
                subject=subject,
                html_body=body,
                reply_to=mailer.sender,
            )
        except Exception as exc:
            log.exception(
                "Weekly report send failed for project %s: %s", project.id, exc
            )
            continue

        emails_sent += 1
        await log_action(
            db,
            user=None,
            action="devlog_project.weekly_report_sent",
            entity_type="devlog_project",
            entity_id=project.id,
            details={
                "to": to_email,
                "hours": hours,
                "phase_changes": len(phase_changes),
                "invoices_sent": len(invoices_sent),
                "invoices_paid": len(invoices_paid),
                "week_start": start_utc.isoformat(),
                "week_end": end_utc.isoformat(),
            },
        )

    await db.commit()
    return {
        "projects_total": len(projects),
        "emails_sent": emails_sent,
        "skipped_no_activity": skipped_no_activity,
        "skipped_no_client_email": skipped_no_client_email,
    }


async def run() -> dict:
    """Wrapper sans session (pour le cron HTTP trigger)."""
    async with AsyncSessionLocal() as db:
        return await run_weekly_client_reports(db)


def main() -> None:
    import asyncio

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = asyncio.run(run())
    log.info("devlog_weekly_client_report: %s", result)


if __name__ == "__main__":
    main()
