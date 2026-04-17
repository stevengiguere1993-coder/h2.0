"""Public webhook receivers (Stripe, QBO, Monday sunset, custom forms).

These endpoints are INTENTIONALLY public but verify a shared secret or
provider signature before accepting any payload.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.api.deps import DBSession
from app.models.contact_request import ContactRequest

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


@router.post(
    "/form",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generic form webhook (Squarespace, Typeform, etc.)",
)
async def webhook_form(
    request: Request,
    db: DBSession,
    x_webhook_secret: str | None = Header(None, alias="x-webhook-secret"),
) -> Dict[str, Any]:
    """Accepts any JSON form payload and stores it as a ContactRequest.

    Used to replicate Monday form webhooks we are sunsetting.
    Payload must include at minimum `name`, `email`, `message`.
    The request is authenticated by the shared header `x-webhook-secret`.
    """
    expected = os.getenv("FORM_WEBHOOK_SECRET")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook not configured",
        )
    if not x_webhook_secret or not _constant_time_eq(x_webhook_secret, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret")

    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expected JSON object")

    name = str(body.get("name") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    message = str(body.get("message") or "").strip()
    if not (name and email and message):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields: name, email, message",
        )

    record = ContactRequest(
        name=name[:255],
        email=email[:320],
        phone=(str(body.get("phone") or "") or None),
        address=(str(body.get("address") or "") or None),
        project_type=str(body.get("project_type") or "autre")[:32],
        budget_range=(str(body.get("budget_range") or "") or None),
        message=message[:5000],
        locale=(str(body.get("locale") or "fr")[:8] if body.get("locale") else "fr"),
        source=str(body.get("source") or "webhook")[:128],
        gdpr_consent=bool(body.get("gdpr_consent", True)),
        marketing_consent=bool(body.get("marketing_consent", False)),
    )
    db.add(record)
    await db.flush()
    return {"ok": True, "id": record.id}


@router.post(
    "/quickbooks",
    status_code=status.HTTP_202_ACCEPTED,
    summary="QuickBooks Online webhook (payment/invoice updates)",
)
async def webhook_quickbooks(
    request: Request,
    intuit_signature: str | None = Header(None, alias="intuit-signature"),
) -> Dict[str, Any]:
    """Validates Intuit's HMAC-SHA256 signature and logs the event."""
    verifier = os.getenv("QBO_WEBHOOK_VERIFIER_TOKEN")
    if not verifier:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook not configured"
        )
    raw = await request.body()
    expected = base64_hmac(verifier, raw)
    if not intuit_signature or not _constant_time_eq(intuit_signature, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    log.info("QBO webhook received: %s", json.dumps(payload)[:2000])
    # TODO(phase2): reconcile invoice status into the factures table.
    return {"ok": True}


def base64_hmac(secret: str, raw: bytes) -> str:
    import base64
    return base64.b64encode(
        hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    ).decode("ascii")
