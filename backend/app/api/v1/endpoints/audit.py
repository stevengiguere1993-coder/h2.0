"""Audit log read endpoint (admin+).

    GET /api/v1/audit?entity_type=soumission&entity_id=42
    GET /api/v1/audit?action=facture.sent&limit=50
    GET /api/v1/audit/changes?window=7d  (résumé IA des PRs mergés)

Les écritures de l'audit DB se font via `app.services.audit.log_action`
depuis le code applicatif. Le `/changes` lit GitHub + IA — pas la DB.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireAdminRole
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


# ── Audit IA des changements de code (PRs mergés) ──────────────────


class ChangesTheme(BaseModel):
    title: str
    bullets: List[str]


class ChangesPR(BaseModel):
    number: int
    title: str
    merged_at: str
    url: str


class ChangesOut(BaseModel):
    window: str
    period_start: str
    period_end: str
    pr_count: int
    headline: str
    themes: List[ChangesTheme]
    prs: List[ChangesPR]
    model_used: Optional[str] = None
    provider: Optional[str] = None
    generated_at: str
    restricted: bool = False


@router.get(
    "/changes",
    response_model=ChangesOut,
    summary="Audit IA des PRs mergés (owner / admin)",
)
async def get_changes(
    user: CurrentUser,
    window: str = Query(
        default="7d",
        pattern=r"^(24h|48h|7d|30d|90d)$",
        description="Fenêtre temporelle",
    ),
    force: bool = False,
) -> ChangesOut:
    role = (getattr(user, "role", None) or "").lower()
    if role not in ("owner", "admin"):
        return ChangesOut(
            window=window,
            period_start="",
            period_end="",
            pr_count=0,
            headline="Accès restreint.",
            themes=[],
            prs=[],
            generated_at="",
            restricted=True,
        )

    from app.services.changelog_audit import get_audit

    audit = await get_audit(window, force=force)
    return ChangesOut(
        window=audit.window,
        period_start=audit.period_start,
        period_end=audit.period_end,
        pr_count=audit.pr_count,
        headline=audit.headline,
        themes=[
            ChangesTheme(title=t.title, bullets=t.bullets)
            for t in audit.themes
        ],
        prs=[
            ChangesPR(
                number=p.number,
                title=p.title,
                merged_at=p.merged_at,
                url=p.url,
            )
            for p in audit.raw_prs
        ],
        model_used=audit.model_used,
        provider=audit.provider,
        generated_at=audit.generated_at,
    )
