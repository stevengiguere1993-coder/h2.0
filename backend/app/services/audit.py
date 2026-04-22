"""Helper to append an AuditLog row.

On l'appelle depuis les endpoints mutatifs importants:
    await log_action(db, user=current_user, action="soumission.sent",
                     entity_type="soumission", entity_id=s.id,
                     details={"to": email})
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User


log = logging.getLogger(__name__)


async def log_action(
    db: AsyncSession,
    *,
    user: Optional[User],
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    try:
        entry = AuditLog(
            user_id=user.id if user else None,
            user_email=user.email if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details_json=(
                json.dumps(details, default=str) if details else None
            ),
        )
        db.add(entry)
        await db.flush()
    except Exception as exc:
        # Never let an audit failure break the actual business action.
        log.warning("audit log failed for %s: %s", action, exc)
