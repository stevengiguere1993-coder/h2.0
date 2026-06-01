"""
Microsoft Graph mailer — sends emails from info@immohorizon.com using
OAuth client-credentials flow (Azure App registration).

Ported from bridge-web; kept minimal and async.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_SEND_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"


@dataclass
class _TokenCache:
    access_token: Optional[str] = None
    expires_at: float = 0.0


@dataclass
class EmailAttachment:
    name: str
    content_bytes: bytes
    content_type: str = "application/octet-stream"


class GraphMailer:
    def __init__(self) -> None:
        self.tenant = settings.azure_tenant_id
        self.client_id = settings.azure_client_id
        self.client_secret = settings.azure_client_secret
        self.sender = settings.mail_from_email
        self._cache = _TokenCache()

    @property
    def ready(self) -> bool:
        return bool(self.tenant and self.client_id and self.client_secret and self.sender)

    async def _token(self) -> str:
        if self._cache.access_token and time.time() < self._cache.expires_at - 60:
            return self._cache.access_token
        if not self.ready:
            raise RuntimeError("Graph mailer is not configured")
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                _TOKEN_URL.format(tenant=self.tenant),
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                },
            )
            r.raise_for_status()
            data = r.json()
        self._cache.access_token = data["access_token"]
        self._cache.expires_at = time.time() + int(data.get("expires_in", 3600))
        return self._cache.access_token  # type: ignore[return-value]

    async def send(
        self,
        to: Iterable[str],
        subject: str,
        html_body: str,
        cc: Optional[Iterable[str]] = None,
        bcc: Optional[Iterable[str]] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[EmailAttachment]] = None,
        internal: bool = False,
    ) -> None:
        token = await self._token()
        to_list = list(to)
        recipients = [{"emailAddress": {"address": addr}} for addr in to_list]
        # Copie cachée de supervision : tout courriel externe (client,
        # fournisseur…) est BCC'd vers settings.client_email_bcc. Les
        # envois internes (internal=True : codes/tests d'auth, rappels
        # au personnel) en sont exclus. On dédoublonne contre to/cc/bcc.
        bcc_list = list(bcc) if bcc else []
        owner = (settings.client_email_bcc or "").strip()
        if owner and not internal:
            already = {
                a.lower()
                for a in (to_list + list(cc or []) + bcc_list)
            }
            if owner.lower() not in already:
                bcc_list.append(owner)
        msg = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": html_body},
                "toRecipients": recipients,
                "from": {"emailAddress": {"address": self.sender, "name": settings.mail_from_name}},
            },
            "saveToSentItems": True,
        }
        if cc:
            msg["message"]["ccRecipients"] = [
                {"emailAddress": {"address": a}} for a in cc
            ]
        if bcc_list:
            msg["message"]["bccRecipients"] = [
                {"emailAddress": {"address": a}} for a in bcc_list
            ]
        if reply_to:
            msg["message"]["replyTo"] = [{"emailAddress": {"address": reply_to}}]
        if attachments:
            import base64
            msg["message"]["attachments"] = [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": a.name,
                    "contentType": a.content_type,
                    "contentBytes": base64.b64encode(a.content_bytes).decode("ascii"),
                }
                for a in attachments
            ]

        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.post(
                _SEND_URL.format(sender=self.sender),
                headers={"Authorization": f"Bearer {token}"},
                json=msg,
            )
            if r.status_code >= 400:
                log.error("Graph sendMail failed: %s %s", r.status_code, r.text)
                r.raise_for_status()


# Singleton
_mailer: Optional[GraphMailer] = None


def get_mailer() -> GraphMailer:
    global _mailer
    if _mailer is None:
        _mailer = GraphMailer()
    return _mailer
