"""Création automatique de tâches QG pour les renouvellements de bail.

Stratégie côté QC :
- Bail >= 12 mois → l'avis de modification doit être envoyé au moins
  3 mois et au plus 6 mois avant l'échéance. On déclenche **5 mois**
  avant pour laisser une marge confortable.
- Bail < 12 mois → 1 à 2 mois avant l'échéance. On déclenche **2 mois**
  avant.

Au lieu d'envoyer l'avis directement par cron (l'utilisateur veut
contrôler le contenu : %/$, motif, vérifier le PDF), on crée une
tâche dans `entreprise_taches` côté QG. Cliquer dessus ouvre
`/immobilier/renouvellements?bail_id=X` qui pré-charge le bail.

Idempotence : tag `bail-renew:{bail_id}` sur la tâche pour ne pas
créer de doublon. Si une tâche existe déjà pour ce bail (peu importe
son status), on skip.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import List

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entreprise_tache import EntrepriseTache, TacheStatus
from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    ImmeubleOwnership,
    Locataire,
    Logement,
)


log = logging.getLogger(__name__)


def _lead_days_for_bail(bail: Bail) -> int:
    """Délai (en jours avant date_fin) où la tâche doit déjà exister."""
    if bail.date_debut and bail.date_fin:
        duration_days = (bail.date_fin - bail.date_debut).days
        if duration_days >= 360:  # ≈ 12 mois
            return 5 * 30
    return 2 * 30


async def _has_existing_task(db: AsyncSession, bail_id: int) -> bool:
    tag_marker = f'"bail-renew:{bail_id}"'
    row = (
        await db.execute(
            select(EntrepriseTache.id).where(
                EntrepriseTache.tags_json.like(f"%{tag_marker}%")
            ).limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def scan_and_create_renew_tasks(
    db: AsyncSession, today: date | None = None
) -> dict:
    """Scan quotidien : crée les tâches QG pour chaque bail dont la
    fenêtre de rappel est ouverte (et pas encore traité)."""
    today = today or date.today()
    now_utc = datetime.now(timezone.utc)

    # Charge tous les baux actifs avec date_fin dans les 7 prochains mois
    horizon = today + timedelta(days=210)
    bails = (
        await db.execute(
            select(Bail).where(
                and_(
                    Bail.status == BailStatus.ACTIF.value,
                    Bail.date_fin >= today,
                    Bail.date_fin <= horizon,
                )
            )
        )
    ).scalars().all()

    created = 0
    skipped = 0
    errors: List[str] = []

    for bail in bails:
        try:
            lead = _lead_days_for_bail(bail)
            trigger = bail.date_fin - timedelta(days=lead)
            if trigger > today:
                continue
            if await _has_existing_task(db, bail.id):
                skipped += 1
                continue

            # Récupère contexte pour le titre lisible
            logement = await db.get(Logement, bail.logement_id)
            immeuble = (
                await db.get(Immeuble, logement.immeuble_id)
                if logement
                else None
            )
            locataire = await db.get(Locataire, bail.locataire_id)

            # Détermine l'entreprise propriétaire (1ère ownership trouvée)
            entreprise_id = None
            if immeuble is not None:
                ownership = (
                    await db.execute(
                        select(ImmeubleOwnership).where(
                            ImmeubleOwnership.immeuble_id == immeuble.id
                        ).limit(1)
                    )
                ).scalar_one_or_none()
                if ownership is not None:
                    entreprise_id = ownership.entreprise_id

            if entreprise_id is None:
                # Pas de propriétaire → on saute, on n'a pas où ranger la tâche.
                errors.append(
                    f"bail {bail.id}: aucune entreprise propriétaire"
                )
                continue

            duration_days = (
                (bail.date_fin - bail.date_debut).days
                if bail.date_debut and bail.date_fin
                else 365
            )
            kind_label = "12 mois" if duration_days >= 360 else "court terme"
            adresse = (
                f"{immeuble.address}{', ' + logement.numero if logement else ''}"
                if immeuble
                else "logement"
            )
            title = (
                f"Préparer le renouvellement de bail ({kind_label}) — {adresse}"
            )
            description = (
                f"Bail #{bail.id} · "
                f"{locataire.full_name if locataire else 'locataire'} · "
                f"loyer actuel {float(bail.loyer_mensuel):.2f} $/m · "
                f"fin {bail.date_fin}.\n\n"
                f"Préparer la hausse, vérifier le PDF puis envoyer l'avis "
                f"officiel depuis /immobilier/renouvellements."
            )

            tags = [f"bail-renew:{bail.id}", "auto-bail-renouvellement"]
            tache = EntrepriseTache(
                entreprise_id=entreprise_id,
                title=title,
                description=description,
                departement="Immobilier",
                status=TacheStatus.TODO.value,
                impact=8,
                confidence=10,
                effort=3,
                due_date=bail.date_fin - timedelta(days=lead - 14),
                tags_json=json.dumps(tags),
            )
            tache.created_at = now_utc
            tache.updated_at = now_utc
            db.add(tache)
            created += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("renew-task bail %s failed", bail.id)
            errors.append(f"bail {bail.id}: {exc!s}"[:240])

    if created:
        await db.commit()

    return {
        "bails_scanned": len(bails),
        "tasks_created": created,
        "tasks_skipped": skipped,
        "errors": errors,
    }
