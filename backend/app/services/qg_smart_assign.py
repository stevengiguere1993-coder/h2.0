"""Suggestion intelligente d'assignation pour une tâche entreprise.

Heuristique simple, transparente et explicable :

  score = -charge_open + dispo_score

  - charge_open  = somme des `effort` (1-10) des tâches ouvertes
                   actuellement assignées au user. Plus c'est élevé,
                   moins l'user est libre. Pondéré par 1.0.
  - dispo_score  = nb d'heures libres dans la fenêtre 7-14j prochains
                   (pas en ExternalBusyBlock). Pondéré 0.5 (heures
                   comptent moins que la charge tâches).

Retourne le top N user avec leur score + raisons + prochain créneau
libre suggéré (≥ 1h consécutif d'ici 7j).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_sync import ExternalBusyBlock
from app.models.entreprise_tache import EntrepriseTache, TacheStatus
from app.models.user import User


_OPEN_STATUSES = {
    TacheStatus.BACKLOG.value,
    TacheStatus.TODO.value,
    TacheStatus.IN_PROGRESS.value,
    TacheStatus.WAITING.value,
}


@dataclass
class AssignSuggestion:
    user_id: int
    full_name: str
    email: str
    score: float
    nb_taches_open: int
    charge_effort: int
    free_hours_next_7d: float
    next_free_slot: Optional[str] = None  # ISO datetime or None
    reasons: List[str] = field(default_factory=list)


async def suggest_assignees(
    db: AsyncSession,
    candidate_users: List[User],
    horizon_days: int = 7,
    top_n: int = 3,
) -> List[AssignSuggestion]:
    """Score chaque candidat et retourne les meilleurs `top_n`."""
    if not candidate_users:
        return []
    user_ids = [u.id for u in candidate_users]

    # 1) Charge : tâches ouvertes par user, somme des efforts
    charge_rows = (
        await db.execute(
            select(
                EntrepriseTache.assignee_user_id,
                func.count(EntrepriseTache.id),
                func.coalesce(func.sum(EntrepriseTache.effort), 0),
            )
            .where(
                and_(
                    EntrepriseTache.assignee_user_id.in_(user_ids),
                    EntrepriseTache.status.in_(list(_OPEN_STATUSES)),
                )
            )
            .group_by(EntrepriseTache.assignee_user_id)
        )
    ).all()
    charge_by_user = {
        row[0]: (int(row[1]), int(row[2] or 0)) for row in charge_rows
    }

    # 2) Disponibilité : busy blocks dans la fenêtre, calcul d'heures libres
    now = datetime.now(timezone.utc)
    horizon_end = now + timedelta(days=horizon_days)
    busy_rows = (
        await db.execute(
            select(ExternalBusyBlock).where(
                and_(
                    ExternalBusyBlock.user_id.in_(user_ids),
                    ExternalBusyBlock.end_at >= now,
                    ExternalBusyBlock.start_at <= horizon_end,
                )
            )
        )
    ).scalars().all()
    busy_by_user: dict[int, list[tuple[datetime, datetime]]] = {}
    for b in busy_rows:
        s = max(b.start_at, now)
        e = min(b.end_at, horizon_end)
        if e <= s:
            continue
        busy_by_user.setdefault(b.user_id, []).append((s, e))

    # 3) Score chaque candidat
    suggestions: List[AssignSuggestion] = []
    for u in candidate_users:
        nb_taches, charge_effort = charge_by_user.get(u.id, (0, 0))
        free_hours, next_slot = _compute_free_hours_and_slot(
            now, horizon_end, busy_by_user.get(u.id, [])
        )
        # Score: plus c'est haut, plus l'user est un bon candidat.
        score = round((-charge_effort * 1.0) + (free_hours * 0.5), 2)

        reasons: List[str] = []
        if nb_taches == 0:
            reasons.append("Aucune tâche ouverte assignée")
        else:
            reasons.append(
                f"{nb_taches} tâche{'s' if nb_taches > 1 else ''} ouverte{'s' if nb_taches > 1 else ''}"
                f" (effort total {charge_effort})"
            )
        reasons.append(f"{free_hours:.1f} h libres d'ici {horizon_days} j")

        suggestions.append(
            AssignSuggestion(
                user_id=u.id,
                full_name=getattr(u, "full_name", None) or u.email,
                email=u.email,
                score=score,
                nb_taches_open=nb_taches,
                charge_effort=charge_effort,
                free_hours_next_7d=round(free_hours, 1),
                next_free_slot=next_slot.isoformat() if next_slot else None,
                reasons=reasons,
            )
        )

    suggestions.sort(key=lambda s: s.score, reverse=True)
    return suggestions[:top_n]


def _compute_free_hours_and_slot(
    start: datetime,
    end: datetime,
    busy: list[tuple[datetime, datetime]],
) -> tuple[float, Optional[datetime]]:
    """Calcule les heures libres (ouvrables 8h-18h) + premier créneau ≥ 1h.

    Pour rester simple, on intersecte la fenêtre [start, end] avec les
    journées ouvrables (lun-ven, 8h-18h locale, mais on travaille en UTC
    et on suppose le décalage est constant) et on retire les busy
    blocks. Résultat : heures totales + datetime du 1er créneau libre
    >= 1h.
    """
    # Construire les fenêtres ouvrables
    workblocks: list[tuple[datetime, datetime]] = []
    cur = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while cur <= end:
        if cur.weekday() < 5:  # 0=Mon, 4=Fri
            wb_start = cur.replace(hour=12, minute=0)  # 8h locale = 12h UTC en hiver QC
            wb_end = cur.replace(hour=22, minute=0)    # 18h locale = 22h UTC
            wb_start = max(wb_start, start)
            wb_end = min(wb_end, end)
            if wb_end > wb_start:
                workblocks.append((wb_start, wb_end))
        cur += timedelta(days=1)

    # Retirer les busy
    busy_sorted = sorted(busy, key=lambda x: x[0])
    free_hours = 0.0
    next_free: Optional[datetime] = None

    for wb_s, wb_e in workblocks:
        # Slot courant = wb, on retire les busy qui le chevauchent
        cur_s = wb_s
        for b_s, b_e in busy_sorted:
            if b_e <= cur_s or b_s >= wb_e:
                continue
            if b_s > cur_s:
                # Créneau libre [cur_s, min(b_s, wb_e)]
                slot_end = min(b_s, wb_e)
                duration_h = (slot_end - cur_s).total_seconds() / 3600
                if duration_h > 0:
                    free_hours += duration_h
                    if next_free is None and duration_h >= 1.0:
                        next_free = cur_s
            cur_s = max(cur_s, b_e)
            if cur_s >= wb_e:
                break
        # Reste après le dernier busy
        if cur_s < wb_e:
            duration_h = (wb_e - cur_s).total_seconds() / 3600
            if duration_h > 0:
                free_hours += duration_h
                if next_free is None and duration_h >= 1.0:
                    next_free = cur_s

    return (free_hours, next_free)
