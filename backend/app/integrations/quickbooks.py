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
import json
import logging
import os
import re
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
        """Pull refresh_token + realm_id + environment from the DB (set
        by the OAuth callback). Falls back to whatever was seeded via
        env vars if the row is missing."""
        if self._db_loaded:
            return
        try:
            async with AsyncSessionLocal() as db:
                row = (
                    await db.execute(select(QboToken).where(QboToken.id == 1))
                ).scalar_one_or_none()
                if row:
                    if row.refresh_token:
                        self.tokens.refresh_token = row.refresh_token
                    # La connexion via OAuth remplit ces deux champs;
                    # on les réutilise pour que le client cible la
                    # bonne compagnie + le bon environnement.
                    if row.realm_id:
                        self.realm_id = row.realm_id
                    if row.environment:
                        self.env = row.environment.lower()
                        self.base_url = (
                            _PROD_API
                            if self.env == "production"
                            else _SANDBOX_API
                        )
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
            if r.status_code >= 400:
                try:
                    body = r.json()
                except Exception:
                    body = {"error": r.text}
                log.error(
                    "QBO token refresh failed: %s %s", r.status_code, body
                )
                err = str(body.get("error") or r.text)
                raise QuickBooksError(
                    "QBO refresh token invalide ou expiré. "
                    "Refais l'autorisation dans QuickBooks et utilise "
                    "POST /api/v1/qbo/refresh-token pour enregistrer "
                    f"le nouveau token. (détail: {err})"
                )
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
            # Capture le `intuit_tid` retourné par QBO sur chaque
            # réponse — Intuit l'utilise comme correlation ID quand on
            # ouvre un support ticket. On le logge systématiquement
            # (info en succès, warning en erreur) pour pouvoir le
            # forwarder à Intuit Support quand on diagnostique.
            intuit_tid = (
                r.headers.get("intuit_tid")
                or r.headers.get("Intuit_Tid")
                or r.headers.get("Intuit-Tid")
                or ""
            )
            if r.status_code >= 400:
                try:
                    payload = r.json()
                except Exception:
                    payload = {"error": r.text}
                log.warning(
                    "QBO %s %s -> %s tid=%s payload=%s",
                    method,
                    path,
                    r.status_code,
                    intuit_tid or "<missing>",
                    payload,
                )
                # Extrait le motif lisible de QBO (Fault.Error[].Detail/
                # Message) et le met EN TÊTE du message — sinon il est
                # coupé à l'affichage (bannière tronquée) derrière le
                # tid + le payload technique.
                reason = ""
                try:
                    errs = (payload.get("Fault") or {}).get("Error") or []
                    if errs:
                        e0 = errs[0]
                        reason = (
                            e0.get("Detail")
                            or e0.get("Message")
                            or ""
                        ).strip()
                except Exception:  # noqa: BLE001
                    reason = ""
                prefix = f"QBO refus : {reason} — " if reason else ""
                raise QuickBooksError(
                    f"{prefix}QBO {method} {path} failed: {r.status_code} "
                    f"(intuit_tid={intuit_tid or 'n/a'}) {payload}"
                )
            if intuit_tid:
                log.info(
                    "QBO %s %s -> %s tid=%s",
                    method,
                    path,
                    r.status_code,
                    intuit_tid,
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

    async def ensure_project(
        self,
        *,
        parent_customer_id: str,
        project_name: str,
    ) -> Dict[str, Any]:
        """Find-or-create un « projet » QBO = sous-client (Job) rattaché
        au client parent. Sert à rattacher des dépenses/coûts à un
        chantier précis, sans le refacturer.

        QBO impose que le DisplayName d'un sous-client soit unique et
        souvent préfixé du parent (« Parent:Projet »). On résout d'abord
        par Job=true + ParentRef ; sinon on crée avec ParentRef +
        Job=true.
        """
        rows = await self.query(
            "SELECT * FROM Customer WHERE Job = true AND "
            f"ParentRef = '{parent_customer_id}' MAXRESULTS 1000"
        )
        for row in rows:
            # Le sous-client peut s'appeler « Projet » ou « Parent:Projet ».
            disp = (row.get("DisplayName") or "")
            fqn = (row.get("FullyQualifiedName") or "")
            if (
                disp == project_name
                or disp.endswith(f":{project_name}")
                or fqn.endswith(f":{project_name}")
            ):
                return row
        body: Dict[str, Any] = {
            "DisplayName": project_name,
            "Job": True,
            "ParentRef": {"value": str(parent_customer_id)},
        }
        data = await self._request(
            "POST", "/customer", json_body=body, params={"minorversion": "70"}
        )
        return data.get("Customer") or data

    async def ensure_class(self, *, name: str) -> Optional[Dict[str, Any]]:
        """Find-or-create une « Classe » QBO (suivi par classe, ex. par
        projet/chantier). Retourne None si le suivi des classes n'est pas
        activé dans la compagnie (l'appelant ignore alors le ClassRef).
        """
        clean = (name or "").strip()
        if not clean:
            return None
        safe = clean.replace("'", "''")
        try:
            rows = await self.query(
                f"SELECT * FROM Class WHERE Name = '{safe}' MAXRESULTS 1"
            )
            if rows:
                return rows[0]
            data = await self._request(
                "POST",
                "/class",
                json_body={"Name": clean[:100]},
                params={"minorversion": "70"},
            )
            return data.get("Class") or data
        except QuickBooksError:
            # Classes désactivées dans la compagnie ou nom invalide :
            # on n'empêche pas la dépense de se créer (sans ClassRef).
            return None

    async def ensure_payment_method(
        self, *, name: str
    ) -> Optional[Dict[str, Any]]:
        """Find-or-create un « mode de paiement » QBO (PaymentMethod,
        ex. « Carte de crédit », « Virement »). Retourne None en cas
        d'échec (on n'empêche pas la dépense de se créer)."""
        clean = (name or "").strip()
        if not clean:
            return None
        safe = clean.replace("'", "''")
        try:
            rows = await self.query(
                f"SELECT * FROM PaymentMethod WHERE Name = '{safe}' "
                "MAXRESULTS 1"
            )
            if rows:
                return rows[0]
            data = await self._request(
                "POST",
                "/paymentmethod",
                json_body={"Name": clean[:31]},
                params={"minorversion": "70"},
            )
            return data.get("PaymentMethod") or data
        except QuickBooksError:
            return None

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

    # ------------------------------------------------------------------
    # Vendors (= fournisseurs)
    # ------------------------------------------------------------------
    async def find_vendor_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        safe = name.replace("'", "''")
        rows = await self.query(
            f"SELECT * FROM Vendor WHERE DisplayName='{safe}' MAXRESULTS 1"
        )
        return rows[0] if rows else None

    async def find_vendor_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        safe = email.replace("'", "''")
        rows = await self.query(
            f"SELECT * FROM Vendor WHERE PrimaryEmailAddr='{safe}' MAXRESULTS 1"
        )
        return rows[0] if rows else None

    async def create_vendor(
        self,
        *,
        display_name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"DisplayName": display_name[:100]}
        if email:
            body["PrimaryEmailAddr"] = {"Address": email}
        if phone:
            body["PrimaryPhone"] = {"FreeFormNumber": phone}
        data = await self._request(
            "POST", "/vendor", json_body=body, params={"minorversion": "70"}
        )
        return data.get("Vendor") or data

    async def ensure_vendor(
        self,
        *,
        display_name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        if email:
            existing = await self.find_vendor_by_email(email)
            if existing:
                return existing
        existing = await self.find_vendor_by_name(display_name)
        if existing:
            return existing
        return await self.create_vendor(
            display_name=display_name, email=email, phone=phone
        )

    # ------------------------------------------------------------------
    # Accounts (Expense / Income lookup for Bill lines)
    # ------------------------------------------------------------------
    async def first_expense_account(self) -> Optional[Dict[str, Any]]:
        # Bill lines doivent référencer un AccountRef de type Expense
        # (souvent « Cost of Goods Sold » ou « Job Materials »). On
        # prend le premier dispo — l'utilisateur peut reclasser dans
        # QB si besoin.
        rows = await self.query(
            "SELECT * FROM Account WHERE AccountType IN ("
            "'Cost of Goods Sold', 'Expense', 'Other Expense'"
            ") MAXRESULTS 1"
        )
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # Bills (= factures fournisseur, ce que charge un PO h2.0)
    # ------------------------------------------------------------------
    async def get_bill(self, bill_id: str) -> Dict[str, Any]:
        data = await self._request("GET", f"/bill/{bill_id}")
        return data.get("Bill") or data

    async def create_bill(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = await self._request(
            "POST", "/bill", json_body=payload, params={"minorversion": "70"}
        )
        return data.get("Bill") or data

    async def update_bill(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Update requires Id + SyncToken in the payload (QBO semantics).
        data = await self._request(
            "POST", "/bill", json_body=payload, params={"minorversion": "70"}
        )
        return data.get("Bill") or data

    # ------------------------------------------------------------------
    # Purchases (= achats déjà payés, charge dépense + paiement direct)
    # ------------------------------------------------------------------
    async def get_purchase(self, purchase_id: str) -> Dict[str, Any]:
        data = await self._request("GET", f"/purchase/{purchase_id}")
        return data.get("Purchase") or data

    async def create_purchase(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = await self._request(
            "POST", "/purchase", json_body=payload,
            params={"minorversion": "70"},
        )
        return data.get("Purchase") or data

    async def update_purchase(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = await self._request(
            "POST", "/purchase", json_body=payload,
            params={"minorversion": "70"},
        )
        return data.get("Purchase") or data

    # ------------------------------------------------------------------
    # Account lookup by Name (utilisé pour le mapping mode paiement)
    # ------------------------------------------------------------------
    async def find_account_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        if not name:
            return None
        # Tolérance : si le nom contient un suffixe de type recopié par
        # erreur depuis l'aide « Lister comptes QBO » (ex.
        # "CC Horizon Olivier Therrien  (Credit Card)"), on le retire —
        # le vrai Name côté QBO n'inclut pas le type.
        cleaned = re.sub(r"\s*\((?:[^()]*)\)\s*$", "", name).strip()
        candidates = [cleaned]
        if name.strip() != cleaned:
            candidates.append(name.strip())
        for cand in candidates:
            safe = cand.replace("'", "''")
            rows = await self.query(
                f"SELECT * FROM Account WHERE Name = '{safe}' MAXRESULTS 1"
            )
            if rows:
                return rows[0]
        return None

    # ------------------------------------------------------------------
    # Attachable upload — joint un fichier (image, PDF) à une entité QBO
    # (Bill, Purchase, Invoice, etc.) via /v3/company/{id}/upload.
    # Utilise un payload multipart : metadata JSON + contenu binaire.
    # ------------------------------------------------------------------
    async def upload_attachment(
        self,
        *,
        entity_type: str,
        entity_id: str,
        file_name: str,
        content_type: str,
        content: bytes,
    ) -> Dict[str, Any]:
        token = await self._access()
        url = f"{self.base_url}/v3/company/{self.realm_id}/upload"

        attachable = {
            "AttachableRef": [
                {
                    "EntityRef": {
                        "type": entity_type,
                        "value": entity_id,
                    }
                }
            ],
            "FileName": file_name,
            "ContentType": content_type,
        }
        # multipart : la métadonnée JSON puis les bytes. Les noms de
        # parts ("file_metadata_01", "file_content_01") doivent
        # correspondre au suffixe d'index, c'est ce qui dit à QBO de les
        # corréler.
        files = [
            (
                "file_metadata_01",
                (
                    "metadata.json",
                    json.dumps(attachable).encode("utf-8"),
                    "application/json",
                ),
            ),
            (
                "file_content_01",
                (file_name, content, content_type),
            ),
        ]
        async with httpx.AsyncClient(timeout=60.0) as http:
            r = await http.post(
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                files=files,
            )
            if r.status_code >= 400:
                try:
                    payload = r.json()
                except Exception:
                    payload = {"error": r.text}
                log.warning(
                    "QBO upload (%s %s) -> %s %s",
                    entity_type, entity_id, r.status_code, payload,
                )
                raise QuickBooksError(
                    f"QBO upload failed: {r.status_code} {payload}"
                )
            return r.json()


_qbo: Optional[QuickBooksClient] = None


def get_qbo() -> QuickBooksClient:
    global _qbo
    if _qbo is None:
        _qbo = QuickBooksClient()
    return _qbo


# Avoid an unused-import warning in tight environments:
_ = urllib.parse
