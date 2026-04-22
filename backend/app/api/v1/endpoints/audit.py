"""Audit log read endpoint (admin+).

    GET /api/v1/audit?entity_type=soumission&entity_id=42
    GET /api/v1/audit?action=facture.sent&limit=50

Les écritures se font via `app.services.audit.log_action(...)` depuis
le code applicatif.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import DBSession, RequireAdminRole
from app.models.audit_log import AuditLog


router = APIRouter(prefix="/audit", tags=["audit"])


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: Optional[int]
    user_email: Optional[str]
    action: str
    entity_type: Optional[str]
    entity_id: Optional[int]
    details_json: Optional[str]
    created_at: datetime


@router.get("", response_model=List[AuditRead])
async def list_audit(
    db: DBSession,
    _: RequireAdminRole,
    entity_type: Optional[str] = Query(default=None),
    entity_id: Optional[int] = Query(default=None),
    action: Optional[str] = Query(default=None),
    user_email: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> List[AuditRead]:
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_email:
        stmt = stmt.where(AuditLog.user_email == user_email)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [AuditRead.model_validate(r) for r in rows]
