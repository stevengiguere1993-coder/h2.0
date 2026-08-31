"""Smoke — proxy des images MMS (/voice/sms/{id}/media/{i}).

Retour Phil 2026-08-31 : une cliente (Danii Desjardins) envoyait des
photos par texto, captées en base mais jamais affichées — les URLs de
média Twilio exigent l'auth Basic du compte, donc il faut un relais
serveur. On vérifie : le stream authentifié, les 404 propres et le
garde-fou anti-SSRF (seuls les médias api.twilio.com sont proxiés).
"""
from __future__ import annotations

import json

from app.models.voice import PhoneNumber, VoiceSms

from .conftest import TestSessionLocal


def _seed_sms(run, media_urls: list[str] | None) -> int:
    suffix = "1" if media_urls else "2"

    async def _go() -> int:
        async with TestSessionLocal() as s:
            pn = PhoneNumber(e164=f"+1438000000{suffix}", provider="twilio")
            s.add(pn)
            await s.flush()
            sms = VoiceSms(
                phone_number_id=pn.id,
                provider_sid=f"MMTEST{suffix}",
                direction="inbound",
                status="received",
                from_e164="+15140000002",
                to_e164="+14380000001",
                body=None,
                media_urls=json.dumps(media_urls) if media_urls else None,
                num_media=len(media_urls or []),
            )
            s.add(sms)
            await s.flush()
            sid = sms.id
            await s.commit()
            return sid

    return run(_go())


def test_mms_media_proxy(client, auth_headers, run, monkeypatch):
    sms_id = _seed_sms(
        run,
        [
            "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages/MM1/Media/ME1",
            "https://evil.example.com/vol-de-creds",
        ],
    )

    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")

    class FakeResp:
        status_code = 200
        content = b"\x89PNGfake"
        headers = {"content-type": "image/png"}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            # L'auth Basic du compte doit accompagner la requête Twilio.
            assert headers and headers.get("Authorization", "").startswith(
                "Basic "
            )
            assert url.startswith("https://api.twilio.com/")
            return FakeResp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    # Média légitime → streamé avec le bon content-type.
    r = client.get(
        f"/api/v1/voice/sms/{sms_id}/media/0", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == b"\x89PNGfake"

    # URL hors Twilio (index 1) → refusée, jamais fetchée (anti-SSRF).
    r2 = client.get(
        f"/api/v1/voice/sms/{sms_id}/media/1", headers=auth_headers
    )
    assert r2.status_code == 404

    # Index hors bornes → 404 propre.
    r3 = client.get(
        f"/api/v1/voice/sms/{sms_id}/media/5", headers=auth_headers
    )
    assert r3.status_code == 404

    # SMS sans média → 404 propre.
    sans = _seed_sms(run, None)
    r4 = client.get(f"/api/v1/voice/sms/{sans}/media/0", headers=auth_headers)
    assert r4.status_code == 404
