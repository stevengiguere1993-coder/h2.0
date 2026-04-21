"""
QuickBooks Online client — OAuth2 with automatic refresh token rotation.

Surface:
- Company info
- Customers: query by email, create, ensure (idempotent)
- Estimates: create, update (future)
- Invoices: get, create (future)

Refresh tokens are rotated on every /tokens/bearer call; the new value
is persisted back to the Render service env var (QBO_REFRESH_TOKEN)
via the Render API so the next boot picks it up.
"""

from __future__ import annotations

import base64
import logging
import os
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.qbo_token import QboToken

log = logging.getLogger(__name__)

_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
_PROD_API = "https://quickbooks.api.intuit.com"
_SANDBOX_API = "https://sandbox-quickbooks.api.intuit.com"


@dataclass
class QBOTokens:
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    access_expires_at: float = 0.0


class QuickBooksError(Exception):
    """Raised by QuickBooksClient helpers when QBO returns a non-2xx."""


class QuickBooksClient:
    def __init__(self) -> None:
        self.client_id = settings.quickbooks_client_id
        self.client_secret = settings.quickbooks_client_secret
        self.realm_id = settings.qbo_realm_id
        self.env = (settings.quickbooks_env or "sandbox").lower()
        self.tokens = QBOTokens(refresh_token=settings.qbo_refresh_token)
        self.base_url = _PROD_API if self.env == "production" else _SANDBOX_API
        # Guard so we only read the DB-persisted refresh token once per
        # process lifetime. If DB has a newer token than the env, use it.
        self._db_loaded = False

    async def _load_refresh_from_db(self) -> None:
        if self._db_loaded:
            return
        try:
            async with AsyncSessionLocal() as db:
                row = (
                    await db.execute(select(QboToken).where(QboToken.id == 1))
                ).scalar_one_or_none()
                if row and row.refresh_token:
                    self.tokens.refresh_token = row.refresh_token
        except Exception as exc:
            log.warning("Could not load QBO refresh token from DB: %s", exc)
        finally:
            self._db_loaded = True

    @property
    def ready(self) -> bool:
        return bool(
            self.client_id
            and self.client_secret
            and self.realm_id
            and self.tokens.refresh_token
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

        new_refresh = data.get("refresh_token")
        if new_refresh:
            # Primary: persist to DB so the rotated refresh token
            # survives backend restarts without any external service.
            try:
                async with AsyncSessionLocal() as db:
                    row = (
                        await db.execute(select(QboToken).where(QboToken.id == 1))
                    ).scalar_one_or_none()
                    if row is None:
                        db.add(QboToken(id=1, refresh_token=new_refresh))
                    else:
                        row.refresh_token = new_refresh
                    await db.commit()
            except Exception as exc:
                log.warning("Could not save rotated QBO refresh token to DB: %s", exc)

            # Secondary (optional): mirror it into the Render env var
            # so a fresh boot still has a valid value before the DB
            # read is wired in (e.g. during local dev).
            render_api_key = os.getenv("RENDER_API_KEY")
            web_service_id = os.getenv("RENDER_WEB_SERVICE_ID")
            if render_api_key and web_service_id:
                try:
                    async with httpx.AsyncClient(timeout=15.0) as http:
                        await http.put(
                            f"https://api.render.com/v1/services/{web_service_id}/env-vars/QBO_REFRESH_TOKEN",
                            headers={"Authorization": f"Bearer {render_api_key}"},
                            json={"value": new_refresh},
                        )
                except Exception as exc:
                    log.warning("Could not persist rotated QBO refresh token to Render: %s", exc)

    async def _access(self) -> str:
        if self.tokens.access_token and time.time() < self.tokens.access_expires_at - 60:
            return self.tokens.access_token
        await self._load_refresh_from_db()
        await self._refresh()
        assert self.tokens.access_token is not None
        return self.tokens.access_token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
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
                params=params,
            )
            if r.status_code >= 400:
                try:
                    payload = r.json()
                except Exception:
                    payload = {"error": r.text}
                log.warning("QBO %s %s -> %s %s", method, path, r.status_code, payload)
                raise QuickBooksError(
                    f"QBO {method} {path} failed: {r.status_code} {payload}"
                )
            return r.json()

    # ------------------------------------------------------------------
    # Company
    # ------------------------------------------------------------------
    async def company_info(self) -> Dict[str, Any]:
        data = await self._request("GET", f"/companyinfo/{self.realm_id}")
        return data.get("CompanyInfo") or data

    async def tax_registration_numbers(self) -> Dict[str, Optional[str]]:
        """Return GST (TPS) and QST (TVQ) registration numbers.

        QBO stores these under CompanyInfo.NameValue custom fields. The
        keys vary per locale; we look at a few common ones (TaxIdNumber,
        GSTRegistrationNumber, QSTRegistrationNumber, TaxID, etc.).
        """
        try:
            ci = await self.company_info()
        except Exception as exc:
            log.warning("Could not fetch QBO CompanyInfo: %s", exc)
            return {"gst": None, "qst": None}

        gst: Optional[str] = None
        qst: Optional[str] = None
        for entry in ci.get("NameValue", []) or []:
            name = (entry.get("Name") or "").lower()
            value = entry.get("Value")
            if not value:
                continue
            if gst is None and any(
                k in name for k in ("gst", "tps", "taxid", "tax_id")
            ):
                gst = str(value)
            if qst is None and any(k in name for k in ("qst", "tvq", "pst")):
                qst = str(value)
        return {"gst": gst, "qst": qst}

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    async def query(self, sql: str) -> List[Dict[str, Any]]:
        """Run a QBO 'query' statement and return the first entity bucket.

        Example:
            await qbo.query("SELECT * FROM Customer WHERE PrimaryEmailAddr='x@y.com'")
        """
        # QBO expects the query as a URL-encoded parameter
        data = await self._request(
            "GET",
            "/query",
            params={"query": sql, "minorversion": "70"},
        )
        qr = data.get("QueryResponse") or {}
        # Return the value of whichever entity list is present
        for key, val in qr.items():
            if isinstance(val, list):
                return val
        return []

    async def find_customer_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        safe = email.replace("'", "''")
        rows = await self.query(
            f"SELECT * FROM Customer WHERE PrimaryEmailAddr='{safe}' MAXRESULTS 1"
        )
        return rows[0] if rows else None

    async def find_customer_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        safe = name.replace("'", "''")
        rows = await self.query(
            f"SELECT * FROM Customer WHERE DisplayName='{safe}' MAXRESULTS 1"
        )
        return rows[0] if rows else None

    async def create_customer(
        self,
        *,
        display_name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        billing_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"DisplayName": display_name}
        if email:
            body["PrimaryEmailAddr"] = {"Address": email}
        if phone:
            body["PrimaryPhone"] = {"FreeFormNumber": phone}
        if billing_address:
            body["BillAddr"] = {"Line1": billing_address}
        data = await self._request(
            "POST", "/customer", json_body=body, params={"minorversion": "70"}
        )
        return data.get("Customer") or data

    async def ensure_customer(
        self,
        *,
        display_name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        billing_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Find-or-create. Prefers email match, falls back to display name."""
        if email:
            existing = await self.find_customer_by_email(email)
            if existing:
                return existing
        existing = await self.find_customer_by_name(display_name)
        if existing:
            return existing
        return await self.create_customer(
            display_name=display_name,
            email=email,
            phone=phone,
            billing_address=billing_address,
        )

    # ------------------------------------------------------------------
    # Items (Service catalog)
    # ------------------------------------------------------------------
    async def first_income_account(self) -> Optional[Dict[str, Any]]:
        rows = await self.query(
            "SELECT * FROM Account WHERE AccountType = 'Income' MAXRESULTS 1"
        )
        return rows[0] if rows else None

    async def find_item_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        safe = name.replace("'", "\\'")
        rows = await self.query(
            f"SELECT * FROM Item WHERE Name = '{safe}' MAXRESULTS 1"
        )
        return rows[0] if rows else None

    async def create_item(
        self, name: str, description: Optional[str] = None
    ) -> Dict[str, Any]:
        income = await self.first_income_account()
        if not income:
            raise QuickBooksError(
                "No QBO Income account available to link the new Item."
            )
        payload: Dict[str, Any] = {
            "Name": name[:100],
            "Type": "Service",
            "IncomeAccountRef": {"value": str(income["Id"])},
        }
        if description:
            payload["Description"] = description[:4000]
        data = await self._request(
            "POST", "/item", json_body=payload, params={"minorversion": "70"}
        )
        return data.get("Item", data)

    async def ensure_item(
        self, name: str, description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Find an Item by name, otherwise create a Service Item."""
        existing = await self.find_item_by_name(name)
        if existing:
            return existing
        return await self.create_item(name, description=description)

    # ------------------------------------------------------------------
    # Estimates
    # ------------------------------------------------------------------
    async def get_estimate(self, estimate_id: str) -> Dict[str, Any]:
        data = await self._request("GET", f"/estimate/{estimate_id}")
        return data.get("Estimate") or data

    async def create_estimate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = await self._request(
            "POST", "/estimate", json_body=payload, params={"minorversion": "70"}
        )
        return data.get("Estimate") or data

    async def update_estimate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update requires Id + SyncToken in the payload (QBO semantics)."""
        data = await self._request(
            "POST", "/estimate", json_body=payload, params={"minorversion": "70"}
        )
        return data.get("Estimate") or data

    # ------------------------------------------------------------------
    # Invoices (kept from previous surface)
    # ------------------------------------------------------------------
    async def get_invoice(self, invoice_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/invoice/{invoice_id}")

    async def create_invoice(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request(
            "POST", "/invoice", json_body=payload, params={"minorversion": "70"}
        )


_qbo: Optional[QuickBooksClient] = None


def get_qbo() -> QuickBooksClient:
    global _qbo
    if _qbo is None:
        _qbo = QuickBooksClient()
    return _qbo


# Avoid an unused-import warning in tight environments:
_ = urllib.parse
