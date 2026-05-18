"""Twilio Voice SDK — génération de tokens + helpers de dispatch.

On utilise les **Access Tokens Twilio** pour autoriser un browser à
s'enregistrer comme un Twilio Client (`identity = "user_<id>"`) et
recevoir/émettre des appels via WebRTC.

Format JWT documenté : https://www.twilio.com/docs/iam/access-tokens

Setup requis dans Twilio (manuel, une fois) :
1. Console → Voice → TwiML Apps → crée une app, note son SID
   - Voice Request URL : https://h2-0.onrender.com/api/v1/voice/twilio/sdk-outbound
2. Console → Account → API Keys → crée une Standard Key (sid + secret)
3. Mets dans Render env :
   - TWILIO_TWIML_APP_SID      (de l'étape 1)
   - TWILIO_API_KEY_SID         (de l'étape 2, commence par "SK…")
   - TWILIO_API_KEY_SECRET      (de l'étape 2)

Sans ces vars : le token endpoint renvoie 503 et le frontend retombe
sur le mode mobile-only existant.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.voice import VoiceClientPresence

log = logging.getLogger(__name__)


PRESENCE_TTL_SEC = 60  # un user est "online" si ping < 60s


def voice_sdk_configured() -> bool:
    return all(
        os.getenv(k)
        for k in (
            "TWILIO_ACCOUNT_SID",
            "TWILIO_API_KEY_SID",
            "TWILIO_API_KEY_SECRET",
            "TWILIO_TWIML_APP_SID",
        )
    )


def client_identity_for_user(user_id: int) -> str:
    """Identité Twilio Client stable et unique par user.

    Format `user_<id>` — utilisé partout (DB presence, TwiML
    `<Client>user_5</Client>`, frontend Device.register).
    """
    return f"user_{int(user_id)}"


def generate_access_token(
    *,
    user_id: int,
    ttl_sec: int = 3600,
) -> Optional[str]:
    """Génère un JWT Twilio Access Token pour le user.

    Retourne None si la configuration Twilio est incomplète.
    """
    if not voice_sdk_configured():
        return None

    account_sid = os.environ["TWILIO_ACCOUNT_SID"]
    key_sid = os.environ["TWILIO_API_KEY_SID"]
    key_secret = os.environ["TWILIO_API_KEY_SECRET"]
    twiml_app_sid = os.environ["TWILIO_TWIML_APP_SID"]
    identity = client_identity_for_user(user_id)

    now = int(time.time())
    payload = {
        "jti": f"{key_sid}-{uuid.uuid4().hex}",
        "iss": key_sid,
        "sub": account_sid,
        "nbf": now,
        "exp": now + int(ttl_sec),
        "grants": {
            "identity": identity,
            "voice": {
                "incoming": {"allow": True},
                "outgoing": {"application_sid": twiml_app_sid},
            },
        },
    }
    return jwt.encode(
        payload,
        key_secret,
        algorithm="HS256",
        headers={"cty": "twilio-fpa;v=1"},
    )


# ---------------------------------------------------------------------
# Présence
# ---------------------------------------------------------------------


async def update_presence(
    db: AsyncSession, *, user_id: int, accepting: bool = True
) -> None:
    """Pingé toutes les 30s par le frontend. Upsert simple."""
    row = (
        await db.execute(
            select(VoiceClientPresence).where(
                VoiceClientPresence.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = VoiceClientPresence(
            user_id=user_id,
            last_seen_at=datetime.now(timezone.utc),
            is_accepting_calls=accepting,
        )
        db.add(row)
    else:
        row.last_seen_at = datetime.now(timezone.utc)
        row.is_accepting_calls = accepting
    await db.flush()


async def list_online_user_ids(db: AsyncSession) -> List[int]:
    """User IDs avec ping < PRESENCE_TTL_SEC et accepting_calls=True."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=PRESENCE_TTL_SEC)
    rows = (
        await db.execute(
            select(VoiceClientPresence.user_id).where(
                VoiceClientPresence.last_seen_at >= cutoff,
                VoiceClientPresence.is_accepting_calls.is_(True),
            )
        )
    ).scalars().all()
    return list(rows)


def build_dial_clients_xml(user_ids: List[int]) -> str:
    """Renvoie une portion `<Client>user_X</Client>` pour chaque user."""
    return "".join(
        f"<Client>{client_identity_for_user(uid)}</Client>" for uid in user_ids
    )
