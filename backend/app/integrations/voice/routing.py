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
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.voice import VoiceBusinessHours, VoiceFilter, VoiceUserCallHours

#: Fuseau par défaut des plages (numéro ET personnes) — Horizon = Montréal.
DEFAULT_TZ = "America/Montreal"


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
    return _within_windows(rows, now)


def _within_windows(rows, now: Optional[datetime] = None) -> bool:
    """« Sommes-nous dans une plage ? » — commun aux heures d'ouverture
    d'un numéro et aux heures d'appel personnelles d'un utilisateur.

    ``rows`` : objets portant ``day_of_week`` (0 = lundi), ``open_time``,
    ``close_time`` et ``timezone``. **Aucune plage → True** (ouvert / joignable
    en tout temps). Sinon True ssi l'heure courante (fuseau de la 1re plage,
    défaut America/Montreal) tombe dans au moins une plage du jour ; une
    plage dont la fin précède le début passe minuit.
    """
    rows = list(rows or [])
    if not rows:
        return True

    # Convertit l'heure courante dans la TZ du 1er row (en pratique on
    # n'utilise qu'une TZ par numéro / par personne).
    try:
        tz = ZoneInfo(getattr(rows[0], "timezone", None) or DEFAULT_TZ)
    except Exception:  # noqa: BLE001 — fuseau inconnu saisi à la main
        tz = ZoneInfo(DEFAULT_TZ)
    current = (now or datetime.now(tz)).astimezone(tz)
    current_dow = current.weekday()  # 0=lun..6=dim
    current_time = current.time()

    for row in rows:
        if row.day_of_week != current_dow:
            continue
        if _between(current_time, row.open_time, row.close_time):
            return True
    return False


# ---------------------------------------------------------------------
# Heures d'appel PERSONNELLES (bug 19, 2026-10-18)
# ---------------------------------------------------------------------
#
# Une personne « qui peut être appelée » définit ses propres plages
# (Profil → Mes heures d'appel, ou Téléphonie → Acheminement pour un
# admin). Hors plage, elle est sautée par TOUS les chemins de transfert
# qui visent une personne (responsable de dossier, membres du projet,
# utilisateurs en ligne, règles d'acheminement) et l'appel passe à la
# cible suivante. Aucune plage = joignable en tout temps.


async def load_user_call_hours(
    db: AsyncSession, user_ids
) -> Dict[int, List[VoiceUserCallHours]]:
    """Plages personnelles des utilisateurs donnés, groupées par user_id
    (absent du dict = aucune plage = joignable en tout temps)."""
    ids = sorted({int(u) for u in (user_ids or []) if u is not None})
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(VoiceUserCallHours).where(
                VoiceUserCallHours.user_id.in_(ids)
            )
        )
    ).scalars().all()
    out: Dict[int, List[VoiceUserCallHours]] = {}
    for r in rows:
        out.setdefault(int(r.user_id), []).append(r)
    return out


async def filter_users_available_now(
    db: AsyncSession, user_ids, *, now: Optional[datetime] = None
) -> List[int]:
    """Sous-liste (ordre conservé, sans doublon) des utilisateurs qui sont
    DANS leurs heures d'appel personnelles en ce moment (ou qui n'en ont
    défini aucune)."""
    ordered: List[int] = []
    for u in user_ids or []:
        if u is None:
            continue
        u = int(u)
        if u not in ordered:
            ordered.append(u)
    if not ordered:
        return []
    hours = await load_user_call_hours(db, ordered)
    return [u for u in ordered if _within_windows(hours.get(u) or [], now)]


async def is_user_available_now(
    db: AsyncSession, user_id: Optional[int], *, now: Optional[datetime] = None
) -> bool:
    """True si l'utilisateur peut recevoir un transfert maintenant (dans
    ses plages, ou aucune plage définie)."""
    if not user_id:
        return False
    return bool(await filter_users_available_now(db, [int(user_id)], now=now))


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
