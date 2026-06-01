"""Daily cron: email each employee their CRM tasks due today.

For every employee with ≥1 non-done SalesTask whose `due_date` is
today, send them a single digest email with all their due tasks.

Usage (Render cron):
    python -m app.jobs.sales_task_reminders
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date
from typing import Dict, List

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.integrations.email_graph import get_mailer
from app.models.client import Client
from app.models.contact_request import ContactRequest
from app.models.employe import Employe
from app.models.sales_task import SalesTask, sales_task_assignees


log = logging.getLogger(__name__)


KIND_LABELS = {
    "suivi": "Suivi",
    "commander_materiel": "Commander matériel",
    "rappel_rdv": "Rappel rendez-vous",
    "autre": "Autre",
}


async def _load_target_label(db, task: SalesTask) -> str:
    if task.client_id:
        c = (
            await db.execute(select(Client).where(Client.id == task.client_id))
        ).scalar_one_or_none()
        if c:
            return f"Client : {c.name}"
    if task.contact_request_id:
        p = (
            await db.execute(
                select(ContactRequest).where(
                    ContactRequest.id == task.contact_request_id
                )
            )
        ).scalar_one_or_none()
        if p:
            return f"Prospect : {p.name}"
    return "—"


def _body(tasks_with_labels: List[tuple[SalesTask, str]]) -> str:
    rows = ""
    for t, target in tasks_with_labels:
        kind = KIND_LABELS.get(t.kind, t.kind)
        time_bit = (
            f" · {t.due_time}" if (not t.all_day and t.due_time) else ""
        )
        rows += (
            f"<li style='margin:0 0 8px 0'>"
            f"<strong>{t.title}</strong> — {kind}{time_bit}"
            f"<br><span style='color:#555;font-size:12px'>{target}"
            f"{' · ' + t.notes if t.notes else ''}</span>"
            f"</li>"
        )
    return f"""\
<div style="font-family:Helvetica,Arial,sans-serif;color:#111;line-height:1.5">
  <p>Bonjour,</p>
  <p>Voici vos tâches de vente à faire aujourd'hui :</p>
  <ul style="padding-left:20px">{rows}</ul>
  <p style="color:#555;font-size:12px;margin-top:20px">
    Horizon Services Immobiliers — CRM
  </p>
</div>
"""


async def run() -> None:
    mailer = get_mailer()
    if not mailer.ready:
        log.warning("Graph mailer not configured — task reminders skipped.")
        return

    today = date.today()

    async with AsyncSessionLocal() as db:
        try:
            # All non-done tasks due today with their assignees.
            stmt = (
                select(SalesTask, sales_task_assignees.c.employe_id)
                .join(
                    sales_task_assignees,
                    sales_task_assignees.c.task_id == SalesTask.id,
                )
                .where(
                    SalesTask.due_date == today,
                    SalesTask.done.is_(False),
                )
            )
            rows = (await db.execute(stmt)).all()

            # Bucket by employee
            by_employe: Dict[int, List[SalesTask]] = defaultdict(list)
            for task, emp_id in rows:
                by_employe[int(emp_id)].append(task)

            sent = 0
            for emp_id, tasks in by_employe.items():
                emp = (
                    await db.execute(
                        select(Employe).where(Employe.id == emp_id)
                    )
                ).scalar_one_or_none()
                if emp is None or not emp.email:
                    continue
                enriched = [
                    (t, await _load_target_label(db, t)) for t in tasks
                ]
                try:
                    await mailer.send(
                        to=[emp.email],
                        subject=(
                            f"{len(tasks)} tâche"
                            f"{'s' if len(tasks) > 1 else ''} aujourd'hui"
                        ),
                        html_body=_body(enriched),
                        internal=True,
                    )
                    sent += 1
                except Exception as exc:
                    log.exception(
                        "Failed to send digest to %s: %s", emp.email, exc
                    )
            log.info(
                "sales-task reminders: %s employees notified", sent
            )
        except Exception:
            raise


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
