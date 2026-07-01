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
from datetime import date, timedelta
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
# API Projets (GraphQL) — distincte de l'API comptable v3. Sert à créer de
# vrais projets QBO (onglet Projets) depuis Kratos. Requiert le scope
# `project-management.project` + un accès Premium API (palier partenaire).
_PROD_GRAPHQL = "https://qb.api.intuit.com/graphql"
_SANDBOX_GRAPHQL = "https://qb-sandbox.api.intuit.com/graphql"


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
    def graphql_url(self) -> str:
        return (
            _PROD_GRAPHQL if self.env == "production" else _SANDBOX_GRAPHQL
        )

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

    async def graphql(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Appel à l'API GraphQL Intuit (Projets, etc.). Distincte de
        l'API REST v3 : autre host, pas de /v3/company/{realm} dans l'URL
        (le realm est porté par le token OAuth). Lève QuickBooksError sur
        erreur HTTP ou erreur GraphQL (champ `errors`)."""
        token = await self._access()
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.post(
                self.graphql_url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "variables": variables or {}},
            )
            try:
                payload = r.json()
            except Exception:
                payload = {"error": r.text}
            if r.status_code >= 400:
                log.warning(
                    "QBO GraphQL -> %s payload=%s", r.status_code, payload
                )
                raise QuickBooksError(
                    f"QBO GraphQL failed: {r.status_code} {payload}"
                )
            errs = payload.get("errors")
            if errs:
                msg = ""
                try:
                    msg = (errs[0].get("message") or "").strip()
                except Exception:  # noqa: BLE001
                    msg = ""
                log.warning("QBO GraphQL errors=%s", errs)
                raise QuickBooksError(
                    f"QBO GraphQL erreur : {msg or errs}"
                )
            return payload.get("data") or {}

    async def create_qbo_project(
        self,
        *,
        parent_customer_id: str,
        name: str,
        start_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Crée un VRAI projet QBO (onglet Projets) sous le client parent,
        via l'API Projets (GraphQL). Retourne le projet créé (id, name,
        status). Requiert le scope `project-management.project` + accès
        Premium API — sinon QBO renvoie une erreur (gérée en amont)."""
        mutation = (
            "mutation CreateProject("
            "$name: String!, $customerId: String!, $start: String) { "
            "projectManagementCreateProject(input: {"
            "name: $name, customer: {id: $customerId}, startDate: $start"
            "}) { project { id name status } } }"
        )
        variables = {
            "name": (name or "Projet")[:100],
            "customerId": str(parent_customer_id),
            "start": start_date,
        }
        data = await self.graphql(mutation, variables)
        node = (
            data.get("projectManagementCreateProject") or {}
        ).get("project") or {}
        return node

    async def find_customer_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        # PrimaryEmailAddr n'est PAS un champ queryable dans QBO (« property
        # 'PrimaryEmailAddr' is not queryable », erreur 400). On résout donc
        # toujours par DisplayName — l'appelant retombe dessus.
        return None

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

    async def _find_subcustomer(
        self, *, parent_customer_id: str, project_name: str
    ) -> Optional[Dict[str, Any]]:
        """Cherche le sous-client / PROJET d'un projet par parent + nom.

        `ParentRef` n'est PAS « queryable » côté QBO (erreur 4001) : on liste
        les clients et on filtre en Python. IMPORTANT : un sous-client
        CONVERTI en « Projet » QB n'est plus forcément `Job = true` → on ne
        filtre donc PAS sur Job (sinon on rate les projets convertis et le
        coût retombe sur le client parent). On compare nom / nom complet.
        """
        rows = await self.query("SELECT * FROM Customer MAXRESULTS 1000")
        target = (project_name or "").strip().lower()
        if not target:
            return None
        for row in rows:
            if str((row.get("ParentRef") or {}).get("value") or "") != str(
                parent_customer_id
            ):
                continue
            disp = (row.get("DisplayName") or "").strip().lower()
            fqn = (row.get("FullyQualifiedName") or "").strip().lower()
            if (
                disp == target
                or disp.endswith(f":{target}")
                or fqn.endswith(f":{target}")
            ):
                return row
        return None

    async def find_subcustomers(
        self, parent_customer_id: str
    ) -> list[Dict[str, Any]]:
        """Liste TOUS les sous-clients / projets sous un client parent
        (ParentRef non queryable → filtre Python). Sert à retrouver le projet
        converti même s'il a été RENOMMÉ (le nom ne correspond plus à
        l'adresse/au nom Kratos)."""
        rows = await self.query("SELECT * FROM Customer MAXRESULTS 1000")
        return [
            row
            for row in rows
            if str((row.get("ParentRef") or {}).get("value") or "")
            == str(parent_customer_id)
        ]

    async def ensure_project(
        self,
        *,
        parent_customer_id: str,
        project_name: str,
        start_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Crée (ou retrouve) le projet QBO d'un chantier Kratos et
        retourne son sous-client v3 (avec `Id` utilisable comme
        CustomerRef sur les factures/coûts).

        Stratégie :
        1. Déjà existant comme sous-client (Job) → on le réutilise.
        2. Sinon on tente de créer un VRAI projet QBO (onglet Projets) via
           l'API Projets (GraphQL), puis on résout le sous-client v3
           correspondant (par parent + nom) pour récupérer son Id.
        3. Si l'API Projets est indisponible (scope/Premium non accordé),
           on retombe sur la création d'un sous-client v3 classique — le
           rattachement facturation/coûts marche, mais le projet
           n'apparaît pas dans l'onglet Projets (l'utilisateur est averti).
        """
        existing = await self._find_subcustomer(
            parent_customer_id=parent_customer_id, project_name=project_name
        )
        if existing:
            return existing

        # 2) Vrai projet QBO via l'API Projets (GraphQL) — seulement si
        # activé (accès Premium accordé + scope obtenu à la reconnexion).
        if settings.qbo_enable_projects_api:
            try:
                await self.create_qbo_project(
                    parent_customer_id=parent_customer_id,
                    name=project_name,
                    start_date=start_date,
                )
                # Le projet créé est un sous-client sous le capot : on le
                # résout en v3 pour obtenir l'Id (CustomerRef).
                resolved = await self._find_subcustomer(
                    parent_customer_id=parent_customer_id,
                    project_name=project_name,
                )
                if resolved:
                    return resolved
                # Créé mais introuvable en v3 (latence d'indexation) : on
                # remonte quand même l'erreur pour fallback sûr.
                raise QuickBooksError(
                    "Projet créé via l'API Projets mais sous-client v3 "
                    "introuvable immédiatement."
                )
            except QuickBooksError as exc:
                log.warning(
                    "API Projets indisponible, fallback sous-client: %s", exc
                )

        # 3) Fallback : sous-client v3 classique (pas d'onglet Projets).
        # `BillWithParent: true` = « Facturer avec le client parent ».
        # C'est REQUIS pour que QBO propose ensuite ce sous-client dans
        # « Nouveau projet → Convertir à partir d'un client rattaché » ;
        # sans ce drapeau, le sous-client n'apparaît pas dans la liste.
        body: Dict[str, Any] = {
            "DisplayName": project_name,
            "Job": True,
            "BillWithParent": True,
            "ParentRef": {"value": str(parent_customer_id)},
        }
        data = await self._request(
            "POST", "/customer", json_body=body, params={"minorversion": "70"}
        )
        return data.get("Customer") or data

    async def list_projects(self) -> List[Dict[str, Any]]:
        """Liste tous les « projets » QBO (sous-clients / Jobs) pour le
        flux de LIAISON : l'utilisateur relie un projet Kratos à un vrai
        projet/sous-client QB existant (id stocké dans Project.qbo_job_id).

        On retourne id, nom affiché, nom complet (« Parent:Projet ») et le
        parent (id + nom) pour que l'UI puisse grouper par client.
        """
        rows = await self.query(
            "SELECT * FROM Customer WHERE Job = true MAXRESULTS 1000"
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            parent = row.get("ParentRef") or {}
            out.append(
                {
                    "id": str(row.get("Id") or ""),
                    "display_name": row.get("DisplayName") or "",
                    "full_name": row.get("FullyQualifiedName") or "",
                    "parent_id": str(parent.get("value") or "") or None,
                    "parent_name": parent.get("name") or None,
                    "active": bool(row.get("Active", True)),
                }
            )
        out.sort(key=lambda r: (r["full_name"] or r["display_name"]).lower())
        return out

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

    @staticmethod
    def _clean_item_name(name: str) -> str:
        """Nom d'Item QB SÛR pour une requête et une création.

        Le langage de requête QBO casse sur les sauts de ligne ET sur les
        apostrophes/guillemets contenus dans le libellé (la chaîne se ferme
        trop tôt → « Encountered <STRING> … »). Le vrai texte détaillé reste
        dans la Description de la ligne (envoyée en JSON, pas en requête) ;
        le NOM d'Item est donc nettoyé : espaces/retours-ligne aplatis,
        apostrophes/guillemets retirés, ':' retiré (réservé aux sous-items),
        borné à 100 car. (limite QBO)."""
        s = " ".join((name or "").split())
        for ch in ("'", "’", "‘", "‛", "`", '"', ":"):
            s = s.replace(ch, " ")
        return " ".join(s.split())[:100]

    async def find_item_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        safe = self._clean_item_name(name)
        if not safe:
            return None
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
        # Même nettoyage qu'à la recherche (sinon QBO refuse le Name et la
        # recherche ne le retrouverait pas ensuite).
        clean_name = self._clean_item_name(name)
        payload: Dict[str, Any] = {
            "Name": clean_name or "Item",
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

    async def find_invoice_by_docnumber(
        self, doc_number: str
    ) -> Optional[Dict[str, Any]]:
        """Retrouve une facture QB par son numéro de document (DocNumber).
        Sert à se RELIER à une facture existante plutôt qu'en recréer une
        en double (erreur 6140 « Numéro de document en double ») quand le
        lien Kratos a été perdu (reset)."""
        clean = (doc_number or "").strip()
        if not clean:
            return None
        safe = clean.replace("'", "''")
        rows = await self.query(
            f"SELECT * FROM Invoice WHERE DocNumber = '{safe}' MAXRESULTS 1"
        )
        return rows[0] if rows else None

    async def create_invoice(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request(
            "POST", "/invoice", json_body=payload, params={"minorversion": "70"}
        )

    async def create_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Crée un Payment client (reçu de paiement) appliqué à une ou
        plusieurs factures via Line[].LinkedTxn — solde la facture côté
        QBO (passe de « En retard » à « Payée »)."""
        return await self._request(
            "POST", "/payment", json_body=payload, params={"minorversion": "70"}
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
        # PrimaryEmailAddr n'est PAS queryable dans QBO (erreur 400) → on
        # résout par DisplayName (l'appelant retombe dessus).
        return None

    async def create_vendor(
        self,
        *,
        display_name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        billing_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"DisplayName": display_name[:100]}
        if email:
            body["PrimaryEmailAddr"] = {"Address": email}
        if phone:
            body["PrimaryPhone"] = {"FreeFormNumber": phone}
        if billing_address:
            body["BillAddr"] = {"Line1": billing_address[:500]}
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
        billing_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if email:
            existing = await self.find_vendor_by_email(email)
            if existing:
                return existing
        existing = await self.find_vendor_by_name(display_name)
        if existing:
            return existing
        return await self.create_vendor(
            display_name=display_name,
            email=email,
            phone=phone,
            billing_address=billing_address,
        )

    async def find_existing_bill(
        self,
        *,
        vendor_id: str,
        total: float,
        txn_date: str,
        day_window: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """Cherche un Bill QB du meme fournisseur, meme total TTC,
        a ~la meme date (anti-doublon avant push)."""
        return await self._find_existing_txn(
            "Bill",
            vendor_id=vendor_id,
            total=total,
            txn_date=txn_date,
            day_window=day_window,
        )

    async def find_existing_purchase(
        self,
        *,
        vendor_id: str,
        total: float,
        txn_date: str,
        day_window: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """Equivalent de find_existing_bill pour les Purchase (achats
        payes directement par carte / cheque)."""
        return await self._find_existing_txn(
            "Purchase",
            vendor_id=vendor_id,
            total=total,
            txn_date=txn_date,
            day_window=day_window,
        )

    async def find_txn_by_docnumber(
        self, entity: str, doc_number: str
    ) -> Optional[Dict[str, Any]]:
        """Cherche un Bill / Purchase QB par son DocNumber (n° de facture
        fournisseur / PO). Signal le PLUS FORT pour éviter de re-créer un
        coût qui existe déjà dans QB (cas migration) → on s'y relie."""
        clean = (doc_number or "").strip()
        if not clean or entity not in ("Bill", "Purchase"):
            return None
        safe = clean.replace("'", "''")
        try:
            rows = await self.query(
                f"SELECT * FROM {entity} WHERE DocNumber = '{safe}' "
                "MAXRESULTS 1"
            )
        except Exception:  # noqa: BLE001
            return None
        return rows[0] if rows else None

    async def _find_existing_txn(
        self,
        entity: str,
        *,
        vendor_id: str,
        total: float,
        txn_date: str,
        day_window: int,
    ) -> Optional[Dict[str, Any]]:
        try:
            d = date.fromisoformat(txn_date[:10])
        except (ValueError, TypeError):
            return None
        lo = (d - timedelta(days=day_window)).isoformat()
        hi = (d + timedelta(days=day_window)).isoformat()
        # On filtre par fenetre de date en SQL (supporte sur Bill et
        # Purchase), puis on confirme fournisseur + montant en Python
        # — VendorRef/EntityRef ne sont pas toujours filtrables en SQL
        # selon l'entite.
        rows = await self.query(
            f"SELECT * FROM {entity} WHERE TxnDate >= '{lo}' "
            f"AND TxnDate <= '{hi}' MAXRESULTS 200"
        )
        vid = str(vendor_id)
        for r in rows:
            ref = r.get("VendorRef") or r.get("EntityRef") or {}
            if str(ref.get("value") or "") != vid:
                continue
            if abs(float(r.get("TotalAmt") or 0) - float(total)) <= 0.01:
                return r
        return None

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

    async def delete_bill(self, bill_id: str) -> bool:
        """Supprime un Bill QB (best-effort). Sert à enlever l'ancien objet
        quand un achat change de type (Bill ↔ Purchase) pour ne pas laisser
        de doublon orphelin. Renvoie False sans lever si l'objet n'existe
        pas / n'est pas un Bill."""
        try:
            cur = await self.get_bill(str(bill_id))
            tok = str(cur.get("SyncToken") or "0")
        except Exception:  # noqa: BLE001
            return False
        try:
            await self._request(
                "POST",
                "/bill",
                json_body={"Id": str(bill_id), "SyncToken": tok},
                params={"operation": "delete", "minorversion": "70"},
            )
            return True
        except Exception:  # noqa: BLE001
            return False

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

    async def delete_purchase(self, purchase_id: str) -> bool:
        """Supprime une Purchase QB (best-effort) — cf. delete_bill."""
        try:
            cur = await self.get_purchase(str(purchase_id))
            tok = str(cur.get("SyncToken") or "0")
        except Exception:  # noqa: BLE001
            return False
        try:
            await self._request(
                "POST",
                "/purchase",
                json_body={"Id": str(purchase_id), "SyncToken": tok},
                params={"operation": "delete", "minorversion": "70"},
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    async def update_purchase(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = await self._request(
            "POST", "/purchase", json_body=payload,
            params={"minorversion": "70"},
        )
        return data.get("Purchase") or data

    # ------------------------------------------------------------------
    # BillPayment (paiement d'un Bill A/P depuis un compte bancaire ou CC)
    # ------------------------------------------------------------------
    async def create_bill_payment(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        data = await self._request(
            "POST", "/billpayment", json_body=payload,
            params={"minorversion": "70"},
        )
        return data.get("BillPayment") or data

    async def delete_bill_payment(self, bp_id: str) -> bool:
        """Supprime un Paiement de facture QB (best-effort). À supprimer
        AVANT le Bill associé quand un achat change de type."""
        try:
            data = await self._request("GET", f"/billpayment/{bp_id}")
            obj = data.get("BillPayment") or data
            tok = str(obj.get("SyncToken") or "0")
        except Exception:  # noqa: BLE001
            return False
        try:
            await self._request(
                "POST",
                "/billpayment",
                json_body={"Id": str(bp_id), "SyncToken": tok},
                params={"operation": "delete", "minorversion": "70"},
            )
            return True
        except Exception:  # noqa: BLE001
            return False

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
