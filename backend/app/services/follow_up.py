"""Cadence + helpers pour le journal de suivi commercial.

Règles de cadence (par défaut, ajustables plus tard) :
- Nouveau prospect : « Premier appel » dans 24 h
- Premier appel logué (outcome != lost/won/not_interested) :
  « Rappel qualification » +48 h ouvrables
- Soumission envoyée : « Confirmer réception » +24 h
- Confirmer réception logué : « Suivi 1 » +48 h ouvrables
- Suivi 1 logué : « Suivi 2 » +72 h
- Suivi 2 logué : « Suivi 3 (final) » +5 jours
- Outcome won / lost / not_interested : on stoppe la cadence

Heures ouvrables = lundi-vendredi, sans tenir compte des fériés
(simplification — on ajoutera la table férié si besoin).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.follow_up import FollowUp


async def suspend_pending_followups(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: int,
    note: Optional[str] = None,
) -> int:
    """Stoppe la cadence de suivi auto encore en attente d'un sujet :
    vide ``next_action_at`` et marque ``overdue_notified`` sur les suivis
    non terminés, afin qu'ils ne tombent pas « en retard ». Utilisé quand
    un RDV est planifié (le RDV remplace les relances auto). Retourne le
    nombre de suivis suspendus."""
    rows = (
        await db.execute(
            select(FollowUp).where(
                FollowUp.subject_type == subject_type,
                FollowUp.subject_id == subject_id,
                FollowUp.next_action_at.is_not(None),
                FollowUp.outcome.notin_(tuple(STOP_OUTCOMES)),
            )
        )
    ).scalars().all()
    for f in rows:
        f.next_action_at = None
        f.overdue_notified = True
        if note:
            f.notes = (f"{f.notes} · " if f.notes else "") + note
    await db.flush()
    return len(rows)


def add_business_hours(start: datetime, hours: float) -> datetime:
    """Avance `start` de `hours` heures ouvrables (Lun–Ven 8h–17h).
    On garde l'heure UTC mais on saute les week-ends. Si le résultat
    tombe un samedi ou dimanche, on pousse au lundi 9h."""
    target = start + timedelta(hours=hours)
    while target.weekday() >= 5:  # 5 = sam, 6 = dim
        # avance au lundi 9h
        days_until_monday = 7 - target.weekday()
        target = datetime.combine(
            (target + timedelta(days=days_until_monday)).date(),
            time(9, 0),
            tzinfo=target.tzinfo or timezone.utc,
        )
    return target


# Plan par défaut — label → délai (heures, ouvrables)
PROSPECT_CADENCE = [
    ("Premier appel", 24, False),
    ("Rappel qualification", 48, True),
    ("Suivi 2", 72, False),
    ("Suivi final", 120, False),
]
SOUMISSION_CADENCE = [
    ("Confirmer réception", 24, False),
    ("Suivi 1", 48, True),
    ("Suivi 2", 72, False),
    ("Suivi final", 120, False),
]

STOP_OUTCOMES = {"won", "lost", "not_interested"}

# Outcomes « on ne l'a pas joint » : au lieu d'avancer la cadence, on
# reprogramme un RAPPEL rapproché → le lead repasse « à rappeler ».
CALLBACK_OUTCOMES = {"voicemail", "no_answer"}
CALLBACK_LABEL = "Rappeler"
CALLBACK_DELAY_HOURS = 4  # heures ouvrables — ajustable


def _next_step(
    cadence: list[tuple[str, int, bool]], current_label: Optional[str]
) -> Optional[tuple[str, datetime]]:
    """Retourne le label + datetime du PROCHAIN step après celui dont
    le label est `current_label`. Si pas trouvé, on commence au premier."""
    now = datetime.now(timezone.utc)
    if current_label is None:
        label, hours, business = cadence[0]
        return (
            label,
            add_business_hours(now, hours) if business else now + timedelta(hours=hours),
        )
    for i, (lbl, _, _) in enumerate(cadence):
        if lbl == current_label and i + 1 < len(cadence):
            next_lbl, hours, business = cadence[i + 1]
            return (
                next_lbl,
                add_business_hours(now, hours)
                if business
                else now + timedelta(hours=hours),
            )
    return None


async def schedule_first_followup(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: int,
    performed_by_user_id: Optional[int] = None,
) -> FollowUp:
    """Crée la 1re entrée de suivi auto (kind=auto, outcome=scheduled)
    avec un next_action_at basé sur la cadence. Appelée à la création
    d'un prospect ou à l'envoi d'une soumission."""
    cadence = (
        PROSPECT_CADENCE if subject_type == "prospect" else SOUMISSION_CADENCE
    )
    step = _next_step(cadence, None)
    label, when = step if step else (None, None)
    fu = FollowUp(
        subject_type=subject_type,
        subject_id=subject_id,
        kind="auto",
        direction="outbound",
        outcome="scheduled",
        notes=(
            "Suivi automatique programmé."
            if subject_type == "prospect"
            else "Suivi automatique post-envoi de soumission."
        ),
        performed_by_user_id=performed_by_user_id,
        next_action_at=when,
        next_action_label=label,
    )
    db.add(fu)
    await db.flush()
    return fu


def compute_next_after_log(
    *,
    subject_type: str,
    last_label: Optional[str],
    outcome: str,
) -> Optional[tuple[str, datetime]]:
    """Donné le label du suivi qu'on vient de logger (ex. « Suivi 1 »)
    et son outcome, calcule la prochaine étape. Retourne None pour
    arrêter la cadence (won/lost/not_interested ou fin de cycle)."""
    if outcome in STOP_OUTCOMES:
        return None
    cadence = (
        PROSPECT_CADENCE if subject_type == "prospect" else SOUMISSION_CADENCE
    )
    # Boîte vocale / pas de réponse → on ne fait pas avancer la cadence :
    # on reprogramme un rappel rapproché. Le prospect réapparaît
    # « À faire : Rappeler » (à rappeler).
    if outcome in CALLBACK_OUTCOMES:
        now = datetime.now(timezone.utc)
        return (CALLBACK_LABEL, add_business_hours(now, CALLBACK_DELAY_HOURS))
    # Après un rappel enfin abouti, on reprend la cadence normale (le label
    # transitoire « Rappeler » est traité comme le 1er palier).
    effective = cadence[0][0] if last_label == CALLBACK_LABEL else last_label
    return _next_step(cadence, effective)
