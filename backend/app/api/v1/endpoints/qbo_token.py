"""Admin endpoint to manually seed/rotate the QBO refresh token.

Use this when the current refresh token is dead (100-day expiry, or
any other reason) and you need to seed a fresh one obtained from the
QuickBooks OAuth Playground or re-authorization flow — without having
to redeploy the backend or touch Render env vars.
"""

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentAdmin, DBSession
from app.models.qbo_token import QboToken


router = APIRouter(prefix="/qbo", tags=["quickbooks"])


class QboTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10, max_length=2048)


class QboTokenResponse(BaseModel):
    ok: bool
    saved_length: int


@router.post(
    "/refresh-token",
    response_model=QboTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Persist a fresh QBO refresh token (admin only)",
)
async def set_qbo_refresh_token(
    data: QboTokenRequest,
    db: DBSession,
    _: CurrentAdmin,
) -> QboTokenResponse:
    token = data.refresh_token.strip()
    row = (
        await db.execute(select(QboToken).where(QboToken.id == 1))
    ).scalar_one_or_none()
    if row is None:
        db.add(QboToken(id=1, refresh_token=token))
    else:
        row.refresh_token = token
    await db.commit()

    # Reset the in-process QBO client so the next sync reads the new
    # refresh token from the DB instead of the stale cached one.
    from app.integrations import quickbooks as qbo_mod

    if qbo_mod._qbo is not None:
        qbo_mod._qbo.tokens.refresh_token = token
        qbo_mod._qbo.tokens.access_token = None
        qbo_mod._qbo.tokens.access_expires_at = 0.0
        qbo_mod._qbo._db_loaded = True

    return QboTokenResponse(ok=True, saved_length=len(token))
