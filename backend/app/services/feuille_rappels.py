"""Rappels des feuilles de temps (Steven, 2026-11-13 — « les 4 volets »).

Tourne une fois par jour dans le méga-cron (``/cron/run/all-daily``) :

1. **Jour vide** : chaque employé de l'équipe (rôles employé et
   gestionnaire) dont le mode de calcul des heures comprend la feuille de
   temps et qui n'a inscrit aucune heure le jour ouvrable précédent
   (lundi → vendredi) reçoit une notification ``feuille_temps_jour_vide``.
2. **Coupure** : le jour de la coupure de la période de paie qui vient de
   finir (Paramètres → Période de paie), les gestionnaires reçoivent une
   notification ``feuilles_a_approuver`` s'il reste des feuilles de cette
   période non approuvées.

Au plus une notification par personne et par jour / période (le titre
porte la date ; un titre déjà envoyé n'est pas renvoyé).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models.notification import Notification
from app.models.timesheet import Timesheet, TimesheetEntry
from app.models.user import User
from app.services import mode_heures, periode_paie

log = logging.getLogger(__name__)

TZ = ZoneInfo("America/Toronto")
ROLES_EQUIPE = ("employee", "manager")
ROLES_GESTION = ("owner", "admin", "manager")

KIND_JOUR_VIDE = "feuille_temps_jour_vide"
KIND_A_APPROUVER = "feuilles_a_approuver"

JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def jour_ouvrable_precedent(aujourd_hui: date) -> date:
    j = aujourd_hui - timedelta(days=1)
    while j.weekday() >= 5:
        j -= timedelta(days=1)
    return j


def _libelle(j: date) -> str:
    return f"{JOURS[j.weekday()]} {j.day} {j.strftime('%m')}/{j.year}"


async def _deja(db, user_id: int, kind: str, title: str) -> bool:
    return (
        await db.execute(
            select(Notification.id).where(
                Notification.user_id == user_id,
                Notification.kind == kind,
                Notification.title == title,
            ).limit(1)
        )
    ).scalar_one_or_none() is not None


async def _heures_du_jour(db, user_ids: list[int], jour: date) -> Dict[int, float]:
    if not user_ids:
        return {}
    sheets = (
        await db.execute(
            select(Timesheet).where(
                Timesheet.user_id.in_(user_ids),
                Timesheet.period_start <= jour,
                Timesheet.period_end >= jour,
            )
        )
    ).scalars().all()
    out: Dict[int, float] = {}
    for s in sheets:
        idx = (jour - s.period_start).days
        rows = (
            await db.execute(
                select(TimesheetEntry.hours).where(
                    TimesheetEntry.timesheet_id == s.id,
                    TimesheetEntry.day_index == idx,
                )
            )
        ).scalars().all()
        out[s.user_id] = out.get(s.user_id, 0.0) + sum(float(h or 0) for h in rows)
    return out


async def rappels_pour_cron(
    db, aujourd_hui: Optional[date] = None
) -> Dict[str, Any]:
    from app.services.notifications import notify

    aujourd_hui = aujourd_hui or datetime.now(TZ).date()
    res: Dict[str, Any] = {"jour_vide": 0, "a_approuver": 0}

    # 1) Jour ouvrable précédent sans heure.
    equipe = (
        await db.execute(
            select(User).where(User.is_active.is_(True), User.role.in_(ROLES_EQUIPE))
        )
    ).scalars().all()
    modes = await mode_heures.modes_pour(db, equipe)
    cibles = [u for u in equipe if mode_heures.compte_feuille(modes[u.id])]
    if aujourd_hui.weekday() < 5 and cibles:
        jour = jour_ouvrable_precedent(aujourd_hui)
        heures = await _heures_du_jour(db, [u.id for u in cibles], jour)
        titre = f"Feuille de temps : aucune heure le {_libelle(jour)}"
        for u in cibles:
            if heures.get(u.id, 0.0) > 0 or await _deja(db, u.id, KIND_JOUR_VIDE, titre):
                continue
            await notify(
                db,
                user_id=u.id,
                kind=KIND_JOUR_VIDE,
                title=titre,
                body="Inscris tes heures de la journée et ce que tu as fait.",
                href="/m/feuille-de-temps",
            )
            res["jour_vide"] += 1

    # 2) Coupure : feuilles de la période finie encore à approuver.
    r = await periode_paie.charger_reglages(db)
    courante = periode_paie.periode_contenant(aujourd_hui, r)
    finie = periode_paie.periode_contenant(courante.debut - timedelta(days=1), r)
    if aujourd_hui == finie.coupure and cibles:
        sheets = (
            await db.execute(
                select(Timesheet).where(
                    Timesheet.user_id.in_([u.id for u in cibles]),
                    Timesheet.period_start <= finie.fin,
                    Timesheet.period_end >= finie.debut,
                    Timesheet.status != "approuve",
                )
            )
        ).scalars().all()
        en_attente = sorted({s.user_id for s in sheets})
        if en_attente:
            noms = {u.id: (u.display_name or u.email) for u in cibles}
            titre = (
                f"{len(en_attente)} feuille(s) de temps à approuver — période du "
                f"{finie.debut.isoformat()} au {finie.fin.isoformat()}"
            )
            corps = "Coupure aujourd'hui. " + ", ".join(noms[i] for i in en_attente)
            gestion = (
                await db.execute(
                    select(User).where(
                        User.is_active.is_(True), User.role.in_(ROLES_GESTION)
                    )
                )
            ).scalars().all()
            for g in gestion:
                if await _deja(db, g.id, KIND_A_APPROUVER, titre):
                    continue
                await notify(
                    db,
                    user_id=g.id,
                    kind=KIND_A_APPROUVER,
                    title=titre,
                    body=corps[:900],
                    href="/entreprises/employes/feuilles-de-temps",
                )
                res["a_approuver"] += 1
    return res
