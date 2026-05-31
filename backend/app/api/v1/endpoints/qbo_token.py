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
from app.core.config import settings
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


class QboDiagResponse(BaseModel):
    # Ce que la config cible aujourd'hui
    active_environment: str
    client_id_tail: str | None = None  # 4 derniers car. (pas le secret)
    # Token en DB (rempli par la reconnexion OAuth)
    db_has_token: bool
    db_environment: str | None = None
    db_realm_id: str | None = None
    # Token seedé via la variable d'env Render QBO_REFRESH_TOKEN
    env_has_token: bool
    env_realm_id: str | None = None
    # Désaccord d'environnement (cause du 403 ApplicationAuthorizationFailed)
    env_mismatch: bool
    # Test réel : un refresh du token courant réussit-il auprès d'Intuit ?
    refresh_ok: bool | None = None
    refresh_error: str | None = None
    # Test décisif : une VRAIE requête API (CompanyInfo) via le client
    # réel — reproduit exactement le chemin du push. C'est ce qui révèle
    # le 403 ApplicationAuthorizationFailed (token OK mais compagnie/env
    # inaccessible).
    api_query_ok: bool | None = None
    api_query_error: str | None = None
    api_company_name: str | None = None


@router.get(
    "/diag",
    response_model=QboDiagResponse,
    summary="Diagnostic QBO : d'où vient le token, env, test refresh (admin)",
)
async def qbo_diag(db: DBSession, _: CurrentAdmin) -> QboDiagResponse:
    """Aide à élucider les 403 ApplicationAuthorizationFailed. N'expose
    jamais le token ni le secret — seulement leur présence/origine, et
    le résultat d'un vrai refresh auprès d'Intuit."""
    active_env = (settings.quickbooks_env or "sandbox").lower()
    cid = settings.quickbooks_client_id or ""
    row = (
        await db.execute(select(QboToken).where(QboToken.id == 1))
    ).scalar_one_or_none()
    db_env = (row.environment or "").lower() if row else None

    out = QboDiagResponse(
        active_environment=active_env,
        client_id_tail=cid[-4:] if cid else None,
        db_has_token=bool(row and row.refresh_token),
        db_environment=db_env or None,
        db_realm_id=(row.realm_id if row else None),
        env_has_token=bool(settings.qbo_refresh_token),
        env_realm_id=settings.qbo_realm_id,
        env_mismatch=bool(db_env and db_env != active_env),
    )

    # Test réel : tente un refresh du token actuellement utilisé.
    try:
        from app.integrations.quickbooks import QuickBooksClient

        client = QuickBooksClient()
        await client._load_refresh_from_db()
        if client.tokens.refresh_token:
            await client._refresh()
            out.refresh_ok = True
        else:
            out.refresh_ok = False
            out.refresh_error = "Aucun refresh token disponible."
    except Exception as exc:  # noqa: BLE001
        out.refresh_ok = False
        out.refresh_error = str(exc)[:300]

    # Test décisif : vraie requête API via le client singleton (même
    # chemin que le push). Reproduit le 403 ApplicationAuthorizationFailed.
    try:
        from app.integrations.quickbooks import get_qbo

        client = get_qbo()
        await client._load_refresh_from_db()
        # query() retourne directement la liste d'entités (bucket).
        rows = await client.query("select * from CompanyInfo")
        out.api_query_ok = True
        try:
            if rows:
                out.api_company_name = rows[0].get("CompanyName")
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        out.api_query_ok = False
        out.api_query_error = str(exc)[:300]

    return out
