"""Microsoft Graph — rencontres Teams (calendrier + transcriptions).

Réutilise le flow client-credentials de :mod:`app.integrations.email_graph`
(même app registration Azure : ``AZURE_TENANT_ID`` / ``AZURE_CLIENT_ID`` /
``AZURE_CLIENT_SECRET``). Permissions d'application supplémentaires
requises côté Entra (admin consent) :

- ``Calendars.Read``                — lire les calendriers des organisateurs
- ``OnlineMeetings.Read.All``       — résoudre une rencontre Teams
- ``OnlineMeetingTranscript.Read.All`` — lire les transcriptions

⚠ Pour l'accès *application* aux onlineMeetings/transcriptions, Microsoft
exige AUSSI une « application access policy » côté Teams (PowerShell,
une fois) :

    New-CsApplicationAccessPolicy -Identity Kratos-Meetings \
        -AppIds "<AZURE_CLIENT_ID>"
    Grant-CsApplicationAccessPolicy -PolicyName Kratos-Meetings -Global

Les boîtes scannées viennent de ``TEAMS_MEETING_USER_EMAILS`` (liste
séparée par virgules, ex. les organisateurs des dailies).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_GRAPH = "https://graph.microsoft.com/v1.0"


@dataclass
class _TokenCache:
    access_token: Optional[str] = None
    expires_at: float = 0.0


_cache = _TokenCache()


def graph_meetings_configured() -> bool:
    """True si les credentials Azure + la liste de boîtes sont configurés."""
    return bool(
        settings.azure_tenant_id
        and settings.azure_client_id
        and settings.azure_client_secret
        and meeting_user_emails()
    )


def meeting_user_emails() -> list[str]:
    """Boîtes (organisateurs) dont on scanne le calendrier."""
    raw = settings.teams_meeting_user_emails or ""
    return [e.strip() for e in raw.split(",") if e.strip()]


async def _token() -> str:
    if _cache.access_token and time.time() < _cache.expires_at - 60:
        return _cache.access_token
    async with httpx.AsyncClient(timeout=15.0) as http:
        r = await http.post(
            _TOKEN_URL.format(tenant=settings.azure_tenant_id),
            data={
                "client_id": settings.azure_client_id,
                "client_secret": settings.azure_client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
        r.raise_for_status()
        data = r.json()
    _cache.access_token = data["access_token"]
    _cache.expires_at = time.time() + int(data.get("expires_in", 3600))
    return _cache.access_token  # type: ignore[return-value]


async def _get(
    http: httpx.AsyncClient, url: str, **params: Any
) -> httpx.Response:
    tok = await _token()
    return await http.get(
        url,
        params=params or None,
        headers={"Authorization": f"Bearer {tok}"},
    )


# ---------------------------------------------------------------------------
# Calendrier → rencontres Teams terminées
# ---------------------------------------------------------------------------


async def list_teams_meetings(
    user_email: str, start: datetime, end: datetime
) -> list[dict]:
    """Évènements Teams du calendrier de ``user_email`` dans la fenêtre.

    Retourne des dicts : {ical_uid, subject, start, end, join_url,
    organizer_email, attendees(list[str])}. Seulement les évènements en
    ligne (joinUrl présent).
    """
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=30.0) as http:
        url = f"{_GRAPH}/users/{user_email}/calendarView"
        params: dict[str, Any] = {
            "startDateTime": start.isoformat(),
            "endDateTime": end.isoformat(),
            "$select": (
                "iCalUId,subject,start,end,onlineMeeting,attendees,"
                "organizer,isOnlineMeeting"
            ),
            "$top": "50",
        }
        while url:
            r = await _get(http, url, **params)
            r.raise_for_status()
            data = r.json()
            for ev in data.get("value", []):
                join = (ev.get("onlineMeeting") or {}).get("joinUrl")
                if not ev.get("isOnlineMeeting") or not join:
                    continue
                attendees = [
                    (a.get("emailAddress") or {}).get("name")
                    or (a.get("emailAddress") or {}).get("address")
                    or "?"
                    for a in ev.get("attendees", [])
                ]
                out.append(
                    {
                        "ical_uid": ev.get("iCalUId"),
                        "subject": ev.get("subject") or "Rencontre Teams",
                        "start": (ev.get("start") or {}).get("dateTime"),
                        "end": (ev.get("end") or {}).get("dateTime"),
                        "join_url": join,
                        "organizer_email": (
                            (ev.get("organizer") or {}).get("emailAddress")
                            or {}
                        ).get("address"),
                        "attendees": attendees,
                    }
                )
            url = data.get("@odata.nextLink") or ""
            params = {}
    return out


async def resolve_online_meeting(
    user_email: str, join_url: str
) -> Optional[str]:
    """Id du onlineMeeting correspondant à un joinUrl (ou None)."""
    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await _get(
            http,
            f"{_GRAPH}/users/{user_email}/onlineMeetings",
            **{"$filter": f"JoinWebUrl eq '{join_url}'"},
        )
        if r.status_code != 200:
            log.warning(
                "resolve_online_meeting %s → HTTP %s : %s",
                user_email,
                r.status_code,
                r.text[:200],
            )
            return None
        items = r.json().get("value", [])
        return items[0]["id"] if items else None


async def fetch_transcript_text(
    user_email: str, meeting_id: str
) -> Optional[str]:
    """Texte de la transcription la plus récente du meeting (ou None)."""
    async with httpx.AsyncClient(timeout=60.0) as http:
        r = await _get(
            http,
            f"{_GRAPH}/users/{user_email}/onlineMeetings/"
            f"{meeting_id}/transcripts",
        )
        if r.status_code != 200:
            log.warning(
                "list transcripts → HTTP %s : %s",
                r.status_code,
                r.text[:200],
            )
            return None
        items = r.json().get("value", [])
        if not items:
            return None
        tid = items[-1]["id"]
        r2 = await _get(
            http,
            f"{_GRAPH}/users/{user_email}/onlineMeetings/"
            f"{meeting_id}/transcripts/{tid}/content",
            **{"$format": "text/vtt"},
        )
        if r2.status_code != 200:
            log.warning(
                "transcript content → HTTP %s : %s",
                r2.status_code,
                r2.text[:200],
            )
            return None
        return vtt_to_text(r2.text)


# ---------------------------------------------------------------------------
# VTT → texte lisible avec interlocuteurs
# ---------------------------------------------------------------------------

_VTT_TS = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d+\s+-->")
_VTT_TAG = re.compile(r"<v\s+([^>]+)>(.*?)</v>", re.DOTALL)


def vtt_to_text(vtt: str) -> str:
    """Convertit un WebVTT Teams en texte « Nom : réplique » dédoublonné."""
    lines: list[str] = []
    last: Optional[str] = None
    for raw in vtt.splitlines():
        line = raw.strip()
        if (
            not line
            or line == "WEBVTT"
            or _VTT_TS.match(line)
            or line.isdigit()
        ):
            continue
        m = _VTT_TAG.search(line)
        if m:
            speaker = m.group(1).strip()
            text = m.group(2).strip()
            entry = f"{speaker} : {text}"
        else:
            entry = line
        if entry and entry != last:
            lines.append(entry)
            last = entry
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Diagnostic (panneau de statut frontend)
# ---------------------------------------------------------------------------


async def probe() -> dict:
    """Teste chaque maillon et retourne un statut détaillé.

    {configured, token_ok, users: [{email, calendar_ok, meetings_ok,
    detail}]} — permet au frontend d'afficher exactement quoi corriger
    (permission manquante, access policy absente, etc.).
    """
    result: dict = {
        "configured": graph_meetings_configured(),
        "user_emails": meeting_user_emails(),
        "token_ok": False,
        "users": [],
    }
    if not result["configured"]:
        return result
    try:
        await _token()
        result["token_ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["token_error"] = str(exc)[:200]
        return result

    from datetime import timedelta, timezone

    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=30.0) as http:
        for email in meeting_user_emails():
            entry: dict = {"email": email}
            try:
                r = await _get(
                    http,
                    f"{_GRAPH}/users/{email}/calendarView",
                    startDateTime=(now - timedelta(days=1)).isoformat(),
                    endDateTime=now.isoformat(),
                    **{"$select": "subject", "$top": "1"},
                )
                entry["calendar_ok"] = r.status_code == 200
                if r.status_code != 200:
                    entry["calendar_error"] = (
                        f"HTTP {r.status_code}: {r.text[:150]}"
                    )
            except Exception as exc:  # noqa: BLE001
                entry["calendar_ok"] = False
                entry["calendar_error"] = str(exc)[:150]
            try:
                r = await _get(
                    http,
                    f"{_GRAPH}/users/{email}/onlineMeetings",
                    **{
                        "$filter": (
                            "JoinWebUrl eq "
                            "'https://teams.microsoft.com/l/meetup-join/probe'"
                        )
                    },
                )
                # 200 (vide) = permission + access policy OK ; 403 =
                # access policy manquante ou permission absente.
                entry["meetings_ok"] = r.status_code == 200
                if r.status_code != 200:
                    entry["meetings_error"] = (
                        f"HTTP {r.status_code}: {r.text[:150]}"
                    )
            except Exception as exc:  # noqa: BLE001
                entry["meetings_ok"] = False
                entry["meetings_error"] = str(exc)[:150]
            result["users"].append(entry)
    return result
