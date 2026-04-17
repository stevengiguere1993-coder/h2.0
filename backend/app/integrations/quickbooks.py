"""
QuickBooks Online client — OAuth2 with automatic refresh token rotation.

Ported from bridge-web. Minimal surface: company profile, create invoice,
query invoice by id. Every refresh persists the new tokens back to
Render via the Render API so credentials survive restarts.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
_PROD_API = "https://quickbooks.api.intuit.com"
_SANDBOX_API = "https://sandbox-quickbooks.api.intuit.com"


@dataclass
class QBOTokens:
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    access_expires_at: float = 0.0


class QuickBooksClient:
    def __init__(self) -> None:
        self.client_id = settings.quickbooks_client_id
        self.client_secret = settings.quickbooks_client_secret
        self.realm_id = settings.qbo_realm_id
        self.env = (settings.quickbooks_env or "sandbox").lower()
        self.tokens = QBOTokens(refresh_token=settings.qbo_refresh_token)
        self.base_url = _PROD_API if self.env == "production" else _SANDBOX_API

    @property
    def ready(self) -> bool:
        return bool(
            self.client_id and self.client_secret and self.realm_id and self.tokens.refresh_token
        )

    async def _refresh(self) -> None:
        if not self.ready:
            raise RuntimeError("QuickBooks client is not configured")
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode("ascii")
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.post(
                _TOKEN_URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {basic}",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.tokens.refresh_token,
                },
            )
            r.raise_for_status()
            data = r.json()

        self.tokens.access_token = data["access_token"]
        self.tokens.refresh_token = data.get("refresh_token") or self.tokens.refresh_token
        self.tokens.access_expires_at = time.time() + int(data.get("expires_in", 3600))

        # Persist refresh token rotation back to Render so the next boot
        # picks up the rotated value (Intuit rotates the refresh token).
        new_refresh = data.get("refresh_token")
        render_api_key = os.getenv("RENDER_API_KEY")
        web_service_id = os.getenv("RENDER_WEB_SERVICE_ID")
        if new_refresh and render_api_key and web_service_id:
            try:
                async with httpx.AsyncClient(timeout=15.0) as http:
                    await http.put(
                        f"https://api.render.com/v1/services/{web_service_id}/env-vars/QBO_REFRESH_TOKEN",
                        headers={"Authorization": f"Bearer {render_api_key}"},
                        json={"value": new_refresh},
                    )
            except Exception as exc:
                log.warning("Could not persist rotated QBO refresh token: %s", exc)

    async def _access(self) -> str:
        if self.tokens.access_token and time.time() < self.tokens.access_expires_at - 60:
            return self.tokens.access_token
        await self._refresh()
        assert self.tokens.access_token is not None
        return self.tokens.access_token

    async def _request(
        self, method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        token = await self._access()
        url = f"{self.base_url}/v3/company/{self.realm_id}{path}"
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.request(
                method,
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=json_body,
            )
            r.raise_for_status()
            return r.json()

    async def company_info(self) -> Dict[str, Any]:
        return await self._request("GET", "/companyinfo/" + str(self.realm_id))

    async def get_invoice(self, invoice_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/invoice/{invoice_id}")

    async def create_invoice(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request("POST", "/invoice?minorversion=70", json_body=payload)


_qbo: Optional[QuickBooksClient] = None


def get_qbo() -> QuickBooksClient:
    global _qbo
    if _qbo is None:
        _qbo = QuickBooksClient()
    return _qbo
