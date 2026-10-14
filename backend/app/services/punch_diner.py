"""Dîner non payé retiré des punchs (Steven, 2026-10-05).

La fiche employé (Construction) porte une case « dîner »
(``Employe.diner_auto``). Cochée, elle fait retirer 30 minutes de dîner
des heures de punch de l'employé, une fois par jour travaillé, quand la
journée punchée dépasse 5 heures (seuil des normes du travail du Québec
pour la période de repas non payée). C'est pour les employés qui restent
punchés pendant le dîner.

Le retrait est NOTÉ sur le punch (``Punch.diner_minutes``) et ``hours``
reste les heures payées : la paie, le coût des projets, la refacturation
et la feuille de temps QuickBooks suivent sans rien changer d'autre.

Règles :
- il s'applique aux journées à partir du jour où la case a été cochée
  (``Employe.diner_depuis``) ; les heures punchées avant ne changent pas ;
- il est décidé quand un punch se FERME (clock-out mobile ou web,
  fermeture automatique de 22 h, saisie manuelle sans choix explicite) ;
- une fois par jour (journée locale de Montréal) : dès qu'un punch de la
  journée porte une décision (retrait automatique, ou choix manuel d'un
  gestionnaire, même « aucun retrait »), plus rien n'est retiré ce jour-là ;
- le retrait va sur le punch qui vient de se fermer s'il dure au moins
  1 h, sinon sur le plus long punch de la journée (jamais sur un punch
  déjà facturé au client) ;
- un gestionnaire l'enlève ou l'ajoute à la main dans la gestion des
  punchs ; ce choix manuel n'est jamais réécrit.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employe import Employe
from app.models.punch import Punch

MONTREAL = ZoneInfo("America/Montreal")

#: Minutes de dîner retirées par journée.
DINER_MINUTES = 30
#: La journée punchée doit DÉPASSER ce nombre d'heures pour qu'on retire
#: le dîner.
SEUIL_JOURNEE_HEURES = 5.0
#: Le punch qui se ferme porte le retrait s'il dure au moins ça ; sinon
#: c'est le plus long punch de la journée.
MIN_PUNCH_HEURES = 1.0


def aujourd_hui_local() -> date:
    return datetime.now(MONTREAL).date()


def jour_local(dt: datetime) -> date:
    """Journée de travail (heure de Montréal) d'un instant."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MONTREAL).date()


def bornes_jour_utc(jour: date) -> tuple[datetime, datetime]:
    """``[début, fin)`` en UTC de la journée locale ``jour``."""
    debut = datetime.combine(jour, time.min, tzinfo=MONTREAL)
    fin = datetime.combine(jour + timedelta(days=1), time.min, tzinfo=MONTREAL)
    return debut.astimezone(timezone.utc), fin.astimezone(timezone.utc)


def heures_brutes(p: Punch) -> float:
    """Heures punchées AVANT le retrait du dîner."""
    return float(p.hours or 0) + (p.diner_minutes or 0) / 60.0


def heures_nettes(brutes: float, diner_minutes: Optional[int]) -> float:
    """Heures payées : heures punchées moins le dîner (jamais négatif)."""
    return round(max(brutes - (diner_minutes or 0) / 60.0, 0.0), 2)


def diner_actif(emp: Optional[Employe], jour: date) -> bool:
    """La case « dîner » de la fiche s'applique-t-elle à ce jour ?"""
    if emp is None or not emp.diner_auto:
        return False
    return emp.diner_depuis is None or jour >= emp.diner_depuis


async def appliquer_diner_auto(
    db: AsyncSession, punch: Punch, emp: Optional[Employe] = None
) -> Optional[Punch]:
    """Retire le dîner sur la journée du ``punch`` qui vient de se fermer,
    si les règles du module s'appliquent. Retourne le punch qui porte le
    retrait (``punch`` ou un autre punch de la journée), sinon None."""
    if punch.started_at is None or punch.ended_at is None or punch.hours is None:
        return None
    if emp is None:
        emp = await db.get(Employe, punch.employe_id)
    jour = jour_local(punch.started_at)
    if not diner_actif(emp, jour):
        return None

    # Les sessions n'auto-flushent pas : le punch qui vient d'être fermé
    # doit être en base pour que la requête de la journée le voie.
    await db.flush()
    debut, fin = bornes_jour_utc(jour)
    journee = list(
        (
            await db.execute(
                select(Punch).where(
                    Punch.employe_id == punch.employe_id,
                    Punch.started_at >= debut,
                    Punch.started_at < fin,
                    Punch.ended_at.is_not(None),
                    Punch.hours.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if punch not in journee:
        journee.append(punch)

    # Une seule décision par jour : retrait déjà posé, ou choix manuel.
    if any(p.diner_minutes is not None for p in journee):
        return None
    if sum(heures_brutes(p) for p in journee) <= SEUIL_JOURNEE_HEURES:
        return None

    cible: Optional[Punch] = None
    if punch.invoiced_at is None and heures_brutes(punch) >= MIN_PUNCH_HEURES:
        cible = punch
    else:
        candidats = sorted(
            (
                p
                for p in journee
                if p.invoiced_at is None
                and heures_brutes(p) > DINER_MINUTES / 60.0
            ),
            key=lambda p: (-heures_brutes(p), p.id or 0),
        )
        cible = candidats[0] if candidats else None
    if cible is None:
        return None

    brutes = heures_brutes(cible)
    cible.diner_minutes = DINER_MINUTES
    cible.hours = heures_nettes(brutes, DINER_MINUTES)
    await db.flush()

    from app.services.audit import log_action

    await log_action(
        db,
        user=None,
        action="punch.diner_retire",
        entity_type="punch",
        entity_id=cible.id,
        details={
            "employe_id": cible.employe_id,
            "jour": jour.isoformat(),
            "minutes": DINER_MINUTES,
            "heures_payees": float(cible.hours),
        },
    )
    if cible is not punch and (cible.approved or cible.qbo_time_activity_id):
        # Un punch déjà approuvé a changé d'heures : la feuille de temps
        # QuickBooks (suivi de projet) suit, comme après une modification
        # manuelle.
        import asyncio as _asyncio

        from app.services.labour_time_qbo import push_punch_time_now

        _asyncio.create_task(push_punch_time_now(int(cible.id)))
    return cible
