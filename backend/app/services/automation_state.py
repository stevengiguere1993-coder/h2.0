"""État dynamique des automatisations : activé/coupé + dernière exécution.

Conçu FAIL-OPEN : si la table n'existe pas encore, ou si une requête
échoue, `is_automation_enabled` renvoie True — une automatisation ne
doit JAMAIS s'arrêter à cause d'un souci du registre (factures, rappels…
sont critiques).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.automations.catalog import CATALOG
from app.db.session import AsyncSessionLocal
from app.models.automation_setting import AutomationSetting
from app.models.cron_run import CronRun

log = logging.getLogger(__name__)


async def is_automation_enabled(key: str) -> bool:
    """True si l'automatisation `key` est active (défaut: True). Ouvre sa
    propre session courte ; fail-open en cas d'erreur."""
    try:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(AutomationSetting.enabled).where(
                        AutomationSetting.key == key
                    )
                )
            ).first()
            if row is None:
                return True
            return bool(row[0])
    except Exception as exc:  # noqa: BLE001
        log.warning("is_automation_enabled(%s) fail-open: %s", key, exc)
        return True


async def set_automation_enabled(
    db, key: str, enabled: bool, *, user_id: Optional[int] = None
) -> None:
    """Active/coupe une automatisation (upsert)."""
    existing = (
        await db.execute(
            select(AutomationSetting).where(AutomationSetting.key == key)
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            AutomationSetting(
                key=key, enabled=enabled, updated_by_user_id=user_id
            )
        )
    else:
        existing.enabled = enabled
        existing.updated_by_user_id = user_id
    await db.flush()


async def list_automation_states(db) -> list[dict]:
    """Catalogue fusionné avec l'état DB (enabled) et la dernière
    exécution connue (`cron_runs`). Best-effort sur les deux jointures."""
    enabled_map: dict[str, bool] = {}
    last_run_map: dict[str, datetime] = {}
    try:
        for k, en in (
            await db.execute(
                select(AutomationSetting.key, AutomationSetting.enabled)
            )
        ).all():
            enabled_map[k] = bool(en)
    except Exception as exc:  # noqa: BLE001
        log.warning("list_automation_states settings failed: %s", exc)
    try:
        for name, ts in (
            await db.execute(select(CronRun.job_name, CronRun.last_run_at))
        ).all():
            last_run_map[name] = ts
    except Exception as exc:  # noqa: BLE001
        log.warning("list_automation_states cron_runs failed: %s", exc)

    out: list[dict] = []
    for a in CATALOG:
        lr = last_run_map.get(a.key)
        out.append(
            {
                "key": a.key,
                "label": a.label,
                "category": a.category,
                "trigger": a.trigger,
                "schedule": a.schedule,
                "description": a.description,
                "controllable": a.controllable,
                "enabled": enabled_map.get(a.key, True),
                "last_run_at": lr.isoformat() if lr else None,
            }
        )
    return out
