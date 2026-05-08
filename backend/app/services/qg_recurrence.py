"""Matérialisation des templates de tâches récurrentes en instances.

Logique du cron quotidien :
- Pour chaque template actif où `next_due - lead_days <= today` :
  · Crée une nouvelle ligne dans `entreprise_taches` (titre, ICE,
    departement, assignee hérités du template + due_date = next_due).
  · Tag la tâche avec `tpl:{template_id}` pour garder la trace.
  · Avance `next_due` selon (every_n, unit).
  · Incrémente `nb_materialized` et stamp `last_materialized_at`.

Idempotence : on évite de créer un doublon en vérifiant qu'il n'existe
pas déjà une tâche avec ce template_id ET cette due_date.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import List

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entreprise_recurrence import FrequenceUnit, TacheTemplate
from app.models.entreprise_tache import EntrepriseTache, TacheStatus
from app.models.entreprise_tache_immeuble import EntrepriseTacheImmeuble


log = logging.getLogger(__name__)


def _advance(d: date, every_n: int, unit: str) -> date:
    """Avance la date selon la fréquence (interval simple)."""
    if unit == FrequenceUnit.JOUR.value:
        return d + timedelta(days=every_n)
    if unit == FrequenceUnit.SEMAINE.value:
        return d + timedelta(weeks=every_n)
    if unit == FrequenceUnit.MOIS.value:
        # Approximation simple : +30 jours × N. Pour un calendrier
        # exact (ex. 30 fév → 28 fév), on pourrait utiliser
        # dateutil.relativedelta mais pas de dépendance ajoutée ici.
        m = d.month - 1 + every_n
        new_year = d.year + (m // 12)
        new_month = (m % 12) + 1
        # clamp day to last day of new month
        try:
            return d.replace(year=new_year, month=new_month)
        except ValueError:
            # ex. 31 → mois plus court : recule au dernier jour valide
            for try_day in (30, 29, 28):
                try:
                    return d.replace(
                        year=new_year, month=new_month, day=try_day
                    )
                except ValueError:
                    continue
            return d.replace(year=new_year, month=new_month, day=28)
    if unit == FrequenceUnit.ANNEE.value:
        try:
            return d.replace(year=d.year + every_n)
        except ValueError:  # 29 fév + 1 an
            return d.replace(year=d.year + every_n, day=28)
    # Fallback
    return d + timedelta(days=every_n)


async def _has_existing_instance(
    db: AsyncSession, template_id: int, due_date: date
) -> bool:
    """Évite les doublons : déjà créé pour ce due_date ?"""
    tag_marker = f'"tpl:{template_id}"'
    rows = (
        await db.execute(
            select(EntrepriseTache.id).where(
                and_(
                    EntrepriseTache.due_date == due_date,
                    EntrepriseTache.tags_json.like(f"%{tag_marker}%"),
                )
            ).limit(1)
        )
    ).scalars().first()
    return rows is not None


async def materialize_due_templates(
    db: AsyncSession, today: date | None = None
) -> dict:
    """Matérialise les tâches dues. Retourne un résumé.

    `today` est paramétrable pour les tests ; default = date du jour.
    """
    today = today or date.today()
    now = datetime.now(timezone.utc)

    templates: List[TacheTemplate] = (
        await db.execute(
            select(TacheTemplate).where(
                TacheTemplate.is_active.is_(True)
            )
        )
    ).scalars().all()

    scanned = len(templates)
    created = 0
    updated_templates = 0
    errors: List[str] = []

    for tpl in templates:
        # Trigger date = next_due - lead_days
        trigger = tpl.next_due - timedelta(days=tpl.lead_days)
        if trigger > today:
            continue

        try:
            if not await _has_existing_instance(db, tpl.id, tpl.next_due):
                tags = [f"tpl:{tpl.id}", "auto-recurrence"]
                # Statut par défaut hérité du template (peut être
                # « a_venir » pour réception en colonne d'attente
                # ou directement « a_faire ») — fallback BACKLOG si
                # le rows DB est ancien et n'a pas la colonne.
                status_val = (
                    getattr(tpl, "default_status", None)
                    or TacheStatus.BACKLOG.value
                )
                tache = EntrepriseTache(
                    entreprise_id=tpl.entreprise_id,
                    title=tpl.title,
                    description=tpl.description,
                    departement=tpl.departement,
                    status=status_val,
                    impact=tpl.impact,
                    confidence=tpl.confidence,
                    effort=tpl.effort,
                    assignee_user_id=tpl.assignee_user_id,
                    due_date=tpl.next_due,
                    tags_json=json.dumps(tags),
                    recurrence=tpl.unit,
                    recurrence_parent_id=tpl.id,
                )
                tache.created_at = now
                tache.updated_at = now
                db.add(tache)
                # Flush pour avoir l'id avant les liens immeubles.
                await db.flush()
                # Attache les immeubles définis sur le template (multi).
                imm_raw = getattr(tpl, "immeuble_ids_json", None)
                if imm_raw:
                    try:
                        imm_ids = json.loads(imm_raw) or []
                    except Exception:  # noqa: BLE001
                        imm_ids = []
                    for imm_id in imm_ids:
                        if not isinstance(imm_id, int):
                            continue
                        db.add(
                            EntrepriseTacheImmeuble(
                                tache_id=tache.id, immeuble_id=imm_id
                            )
                        )
                created += 1

            # Avance le template peu importe (idempotent + évite boucle)
            tpl.next_due = _advance(tpl.next_due, tpl.every_n, tpl.unit)
            tpl.last_materialized_at = now
            tpl.nb_materialized = (tpl.nb_materialized or 0) + 1
            tpl.updated_at = now
            updated_templates += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("materialize template %s failed", tpl.id)
            errors.append(f"template {tpl.id}: {exc!s}"[:240])

    if created or updated_templates:
        await db.commit()

    return {
        "templates_scanned": scanned,
        "taches_created": created,
        "templates_updated": updated_templates,
        "errors": errors,
    }
