"""Routage Phase 3 : décide quoi faire à l'arrivée d'un appel entrant.

Évalué dans l'ordre :

1. **Blocklist** — si l'appelant matche un filtre `kind='block'`, on
   rejette (Reject TwiML, tonalité d'occupation).
2. **Whitelist VIP** — si l'appelant matche un filtre `kind='vip'`, on
   sonne **direct** chez `forward_to_e164` sans passer par la secrétaire.
3. **Heures d'ouverture** — si des `VoiceBusinessHours` existent pour
   ce numéro et que l'heure actuelle est hors plage, on bascule en
   voicemail IA (record + transcribe Twilio + résumé Claude).
4. **Secrétaire IA** (Phase 2) si `secretary_mode_active=true`.
5. **Transfert direct** (Phase 1) sinon.

Le matching de pattern E.164 supporte :
- Match exact : ``+14385551234`` == ``+14385551234``
- Préfixe wildcard : ``+1438*`` matche tout ce qui commence par ``+1438``
- ``None`` (NULL) : match-tout (catch-all) — typiquement utilisé pour
  une blocklist globale.
"""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum
from typing import List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.voice import VoiceBusinessHours, VoiceFilter


class RoutingAction(str, Enum):
    BLOCK = "block"
    VIP = "vip"
    VOICEMAIL = "voicemail"
    SECRETARY = "secretary"
    FORWARD = "forward"


def matches_pattern(pattern: Optional[str], e164: str) -> bool:
    """Compare un numéro E.164 à un pattern (exact / préfixe* / NULL)."""
    if pattern is None or pattern.strip() == "":
        return True
    p = pattern.strip()
    if p.endswith("*"):
        return e164.startswith(p[:-1])
    return e164 == p


async def is_within_business_hours(
    db: AsyncSession,
    *,
    phone_number_id: int,
    now: Optional[datetime] = None,
) -> bool:
    """Retourne True si on est dans une plage configurée.

    Si aucune plage n'existe pour ce numéro → True (ouvert 24/7).
    Sinon : True ssi l'heure courante (timezone de la 1re plage trouvée
    pour ce jour, défaut America/Montreal) tombe dans au moins une plage.
    """
    rows = (
        await db.execute(
            select(VoiceBusinessHours).where(
                VoiceBusinessHours.phone_number_id == phone_number_id
            )
        )
    ).scalars().all()
    if not rows:
        return True

    # Convertit l'heure courante dans la TZ du 1er row (en pratique on
    # n'utilise qu'une TZ par numéro).
    tz = ZoneInfo(rows[0].timezone or "America/Montreal")
    current = (now or datetime.now(tz)).astimezone(tz)
    current_dow = current.weekday()  # 0=lun..6=dim
    current_time = current.time()

    for row in rows:
        if row.day_of_week != current_dow:
            continue
        if _between(current_time, row.open_time, row.close_time):
            return True
    return False


def _between(t: time, open_: time, close: time) -> bool:
    if close <= open_:
        # Plage qui passe minuit (rare). On considère que t est dans
        # la plage s'il est ≥ open OU ≤ close.
        return t >= open_ or t <= close
    return open_ <= t <= close


async def decide_routing(
    db: AsyncSession,
    *,
    phone_number_id: int,
    from_e164: str,
    secretary_mode_active: bool,
    now: Optional[datetime] = None,
) -> RoutingAction:
    """Évalue les règles Phase 3 et retourne l'action à exécuter."""
    filters: List[VoiceFilter] = (
        await db.execute(
            select(VoiceFilter).where(
                VoiceFilter.phone_number_id == phone_number_id,
                VoiceFilter.active.is_(True),
            )
        )
    ).scalars().all()

    # Blocklist priorité absolue.
    for f in filters:
        if f.kind == "block" and matches_pattern(f.pattern, from_e164):
            return RoutingAction.BLOCK

    # VIP : on shortcut la secrétaire.
    for f in filters:
        if f.kind == "vip" and matches_pattern(f.pattern, from_e164):
            return RoutingAction.VIP

    # Heures d'ouverture.
    if not await is_within_business_hours(
        db, phone_number_id=phone_number_id, now=now
    ):
        return RoutingAction.VOICEMAIL

    if secretary_mode_active:
        return RoutingAction.SECRETARY

    return RoutingAction.FORWARD
