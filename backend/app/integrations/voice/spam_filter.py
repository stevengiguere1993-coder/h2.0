"""Anti-spam multi-couches — protection budget Twilio.

Évalué AVANT toute action coûteuse (Polly TTS, Claude API, Dial leg).
Renvoie une décision `SpamCheckResult` qui pilote la réponse TwiML :

- ALLOW          → on continue le flow normal
- BLOCK_CAP      → on bascule sur voicemail-only (cap journalier atteint)
- BLOCK_GEO      → on raccroche poliment (numéro hors NANP)
- BLOCK_STIR     → on raccroche (STIR/SHAKEN failed)
- BLOCK_RATE     → on bloque (rate limit dépassé, auto-ban 24h)
- BLOCK_HONEYPOT → on bloque (3+ raccrochages spam en moins de 2 sec)
- BLOCK_LOOKUP   → on bloque (VoIP non-CNAM = très souvent telemarketer)

Toutes les décisions sont enregistrées dans `voice_usage_daily.spam_blocked`
pour reporting.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.voice.lookup import twilio_lookup
from app.models.voice import (
    Call,
    VoiceCallerIntel,
    VoiceUsageDaily,
)

log = logging.getLogger(__name__)


# Limites par défaut — overridables via env.
MAX_CALLS_PER_HOUR = int(os.getenv("VOICE_MAX_CALLS_PER_HOUR", "3"))
MAX_CALLS_PER_7D = int(os.getenv("VOICE_MAX_CALLS_PER_7D", "20"))
AUTO_BAN_HOURS = int(os.getenv("VOICE_AUTO_BAN_HOURS", "24"))
HONEYPOT_THRESHOLD = int(os.getenv("VOICE_HONEYPOT_THRESHOLD", "3"))
DAILY_COST_CAP_CENTS = int(os.getenv("VOICE_DAILY_COST_CAP_CENTS", "500"))  # $5
LOOKUP_TTL_DAYS = int(os.getenv("VOICE_LOOKUP_TTL_DAYS", "30"))


class SpamCheckResult(str, Enum):
    ALLOW = "allow"
    BLOCK_CAP = "block_cap"
    BLOCK_GEO = "block_geo"
    BLOCK_STIR = "block_stir"
    BLOCK_RATE = "block_rate"
    BLOCK_HONEYPOT = "block_honeypot"
    BLOCK_LOOKUP = "block_lookup"


@dataclass
class SpamCheck:
    result: SpamCheckResult
    reason: str
    intel: Optional[VoiceCallerIntel] = None


def _today_str() -> str:
    return date.today().isoformat()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------
# Daily cost cap
# ---------------------------------------------------------------------


async def is_daily_cap_exceeded(db: AsyncSession) -> tuple[bool, int]:
    """Retourne (exceeded, cents_spent_today)."""
    if DAILY_COST_CAP_CENTS <= 0:
        return (False, 0)
    row = (
        await db.execute(
            select(VoiceUsageDaily).where(
                VoiceUsageDaily.usage_date == _today_str()
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return (False, 0)
    return (row.cents_spent >= DAILY_COST_CAP_CENTS, row.cents_spent)


async def record_call_cost(
    db: AsyncSession, *, duration_sec: int, direction: str
) -> None:
    """Incrémente le compteur journalier après un appel terminé.

    Tarifs Twilio Canada (oct. 2025) — peu sensibles aux variations :
        Voice inbound local CA  : 0.0085 USD/min
        Voice outbound CA       : 0.013  USD/min
    On arrondit la minute supérieure (convention Twilio).
    """
    if duration_sec <= 0:
        return
    minutes = (duration_sec + 59) // 60
    rate = 1.3 if direction == "outbound" else 0.85  # cents/min
    cents = max(1, int(round(minutes * rate)))

    row = (
        await db.execute(
            select(VoiceUsageDaily).where(
                VoiceUsageDaily.usage_date == _today_str()
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = VoiceUsageDaily(
            usage_date=_today_str(), cents_spent=cents, calls_count=1
        )
        db.add(row)
    else:
        row.cents_spent += cents
        row.calls_count += 1
    await db.flush()


async def record_spam_block(db: AsyncSession) -> None:
    """Incrémente le compteur de spam bloqué (stat reporting)."""
    row = (
        await db.execute(
            select(VoiceUsageDaily).where(
                VoiceUsageDaily.usage_date == _today_str()
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = VoiceUsageDaily(
            usage_date=_today_str(), cents_spent=0, calls_count=0, spam_blocked=1
        )
        db.add(row)
    else:
        row.spam_blocked += 1
    await db.flush()


# ---------------------------------------------------------------------
# Intel (load or create)
# ---------------------------------------------------------------------


async def get_or_create_intel(
    db: AsyncSession, from_e164: str
) -> VoiceCallerIntel:
    intel = (
        await db.execute(
            select(VoiceCallerIntel).where(VoiceCallerIntel.from_e164 == from_e164)
        )
    ).scalar_one_or_none()
    if intel is None:
        intel = VoiceCallerIntel(from_e164=from_e164)
        db.add(intel)
        await db.flush()
    return intel


# ---------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------


async def check_incoming(
    db: AsyncSession,
    *,
    from_e164: str,
    verstat: Optional[str] = None,
) -> SpamCheck:
    """Évalue les 6 couches dans l'ordre du moins coûteux au plus coûteux.

    Le seul appel API externe (Twilio Lookup, ~0,005 $) n'est fait que
    si le numéro est nouveau ou si la dernière donnée a > 30 jours.
    """
    # 1. Daily cap
    exceeded, _ = await is_daily_cap_exceeded(db)
    if exceeded:
        return SpamCheck(
            SpamCheckResult.BLOCK_CAP,
            f"daily cap reached ({DAILY_COST_CAP_CENTS}¢) — voicemail only",
        )

    # 2. Geo filter (NANP = +1 only)
    if not from_e164 or not from_e164.startswith("+1"):
        return SpamCheck(
            SpamCheckResult.BLOCK_GEO,
            f"non-NANP caller blocked: {from_e164!r}",
        )

    # 3. STIR/SHAKEN attestation
    if verstat:
        normalized = verstat.lower()
        if "failed" in normalized:
            return SpamCheck(
                SpamCheckResult.BLOCK_STIR,
                f"STIR/SHAKEN failed: {verstat}",
            )

    intel = await get_or_create_intel(db, from_e164)
    if verstat:
        intel.last_verstat = verstat[:64]

    # 3b. Ban explicite ?
    if intel.banned_until and intel.banned_until > _now_utc():
        return SpamCheck(
            SpamCheckResult.BLOCK_RATE,
            f"banned until {intel.banned_until.isoformat()}",
            intel=intel,
        )

    # 4. Rate limit (compteurs glissants depuis voice_calls)
    one_hour_ago = _now_utc() - timedelta(hours=1)
    seven_days_ago = _now_utc() - timedelta(days=7)
    count_1h = (
        await db.execute(
            select(func.count(Call.id)).where(
                Call.from_e164 == from_e164, Call.started_at >= one_hour_ago
            )
        )
    ).scalar_one() or 0
    count_7d = (
        await db.execute(
            select(func.count(Call.id)).where(
                Call.from_e164 == from_e164, Call.started_at >= seven_days_ago
            )
        )
    ).scalar_one() or 0

    if count_1h >= MAX_CALLS_PER_HOUR or count_7d >= MAX_CALLS_PER_7D:
        intel.banned_until = _now_utc() + timedelta(hours=AUTO_BAN_HOURS)
        return SpamCheck(
            SpamCheckResult.BLOCK_RATE,
            f"rate limit: {count_1h}/h or {count_7d}/7d — banned {AUTO_BAN_HOURS}h",
            intel=intel,
        )

    # 5. Honeypot (raccrochages spam précédents)
    if intel.spam_hangup_count >= HONEYPOT_THRESHOLD:
        intel.banned_until = _now_utc() + timedelta(days=30)
        return SpamCheck(
            SpamCheckResult.BLOCK_HONEYPOT,
            f"honeypot: {intel.spam_hangup_count} spam hangups",
            intel=intel,
        )

    # 6. Twilio Lookup (cache 30j) — coûteux, en dernier
    needs_lookup = (
        intel.line_type is None
        or intel.last_lookup_at is None
        or (_now_utc() - intel.last_lookup_at).days >= LOOKUP_TTL_DAYS
    )
    if needs_lookup:
        result = await twilio_lookup(from_e164)
        if result is not None:
            intel.line_type = result.line_type
            intel.caller_name = result.caller_name
            intel.last_lookup_at = _now_utc()

    # VoIP + jamais appelé + pas de CNAM = drapeau rouge typique des
    # robocalls. On bloque le 1er appel. Si c'est légitime, l'appelant
    # rappellera et `count_7d` sera > 0 — on laissera passer.
    if (
        intel.line_type == "voip"
        and not intel.caller_name
        and count_7d == 0
    ):
        return SpamCheck(
            SpamCheckResult.BLOCK_LOOKUP,
            "first call from anonymous VoIP",
            intel=intel,
        )

    return SpamCheck(SpamCheckResult.ALLOW, "passed all checks", intel=intel)


# ---------------------------------------------------------------------
# Honeypot trigger (depuis le webhook de fin d'appel)
# ---------------------------------------------------------------------


HONEYPOT_HANGUP_SEC = 2


async def maybe_mark_honeypot(
    db: AsyncSession, *, from_e164: str, duration_sec: int
) -> None:
    """Si l'appel s'est terminé sous HONEYPOT_HANGUP_SEC, c'est un
    raccrochage suspect (robocall qui scan). On incrémente le compteur."""
    if duration_sec <= 0 or duration_sec > HONEYPOT_HANGUP_SEC:
        return
    intel = await get_or_create_intel(db, from_e164)
    intel.spam_hangup_count += 1
    log.info(
        "Honeypot hit on %s (%d hangups, dur=%ds)",
        from_e164,
        intel.spam_hangup_count,
        duration_sec,
    )
    await db.flush()
