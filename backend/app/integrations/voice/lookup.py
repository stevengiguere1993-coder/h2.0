"""Twilio Lookup API v2 — récupère line_type / caller_name d'un numéro.

Coût : ~0,005 $ par lookup. On cache 30 jours dans `voice_caller_intel`
pour éviter de payer plusieurs fois pour le même numéro.

Docs : https://www.twilio.com/docs/lookup/v2-api
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

LOOKUP_URL = "https://lookups.twilio.com/v2/PhoneNumbers"

log = logging.getLogger(__name__)


@dataclass
class LookupResult:
    line_type: Optional[str]  # mobile|landline|voip|toll_free|personal|uan|unknown
    caller_name: Optional[str]
    raw: dict


async def twilio_lookup(e164: str, timeout: float = 5.0) -> Optional[LookupResult]:
    """Fait un lookup Twilio. Retourne None si non configuré ou erreur."""
    sid = os.getenv("TWILIO_ACCOUNT_SID") or ""
    tok = os.getenv("TWILIO_AUTH_TOKEN") or ""
    if not (sid and tok and e164):
        return None

    # Demande line_type_intelligence + caller_name (US/CA seulement).
    url = f"{LOOKUP_URL}/{e164}"
    params = {"Fields": "line_type_intelligence,caller_name"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params=params, auth=(sid, tok))
            if resp.status_code == 404:
                return LookupResult(line_type="unknown", caller_name=None, raw={})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("Twilio Lookup failed for %s: %s", e164, exc)
        return None

    lti = data.get("line_type_intelligence") or {}
    cn = data.get("caller_name") or {}
    return LookupResult(
        line_type=(lti.get("type") or "unknown").lower(),
        caller_name=cn.get("caller_name") or None,
        raw=data,
    )
