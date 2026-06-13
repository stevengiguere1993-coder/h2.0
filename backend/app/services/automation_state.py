"""État dynamique des automatisations : activé/coupé + dernière exécution.

Conçu FAIL-OPEN : si la table n'existe pas encore, ou si une requête
échoue, `is_automation_enabled` renvoie True — une automatisation ne
doit JAMAIS s'arrêter à cause d'un souci du registre (factures, rappels…
sont critiques).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select

from app.automations.catalog import CATALOG
from app.db.session import AsyncSessionLocal
from app.models.automation_setting import AutomationSetting
from app.models.cron_run import CronRun

log = logging.getLogger(__name__)


async def get_automation_config(key: str) -> dict[str, Any]:
    """Config (dict) d'une automatisation. FAIL-SAFE : {} en cas d'erreur
    ou de table/colonne absente — le job retombe alors sur ses défauts."""
    try:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(AutomationSetting.config_json).where(
                        AutomationSetting.key == key
                    )
                )
            ).first()
            if row is None or not row[0]:
                return {}
            data = json.loads(row[0])
            return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        log.warning("get_automation_config(%s) fail-safe: %s", key, exc)
        return {}


async def get_automation_int(key: str, param: str, default: int) -> int:
    """Helper typé pour un paramètre entier (cadence, délai…)."""
    cfg = await get_automation_config(key)
    try:
        val = int(cfg.get(param, default))
        return val if val > 0 else default
    except (TypeError, ValueError):
        return default


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


async def set_automation_config(
    db, key: str, config: dict, *, user_id: Optional[int] = None
) -> None:
    """Enregistre la config (JSON) d'une automatisation (upsert)."""
    payload = json.dumps(config)
    existing = (
        await db.execute(
            select(AutomationSetting).where(AutomationSetting.key == key)
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            AutomationSetting(
                key=key,
                enabled=True,
                config_json=payload,
                updated_by_user_id=user_id,
            )
        )
    else:
        existing.config_json = payload
        existing.updated_by_user_id = user_id
    await db.flush()


async def list_automation_states(db) -> list[dict]:
    """Catalogue fusionné avec l'état DB (enabled) et la dernière
    exécution connue (`cron_runs`). Best-effort sur les deux jointures."""
    enabled_map: dict[str, bool] = {}
    config_map: dict[str, dict] = {}
    last_run_map: dict[str, datetime] = {}
    try:
        for k, en, cfg in (
            await db.execute(
                select(
                    AutomationSetting.key,
                    AutomationSetting.enabled,
                    AutomationSetting.config_json,
                )
            )
        ).all():
            enabled_map[k] = bool(en)
            if cfg:
                try:
                    parsed = json.loads(cfg)
                    if isinstance(parsed, dict):
                        config_map[k] = parsed
                except Exception:  # noqa: BLE001
                    pass
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
        cfg = config_map.get(a.key, {})
        params = [
            {
                "key": p.key,
                "label": p.label,
                "type": p.type,
                "default": p.default,
                "help": p.help,
                "value": cfg.get(p.key, p.default),
            }
            for p in a.params
        ]
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
                "params": params,
            }
        )
    return out
