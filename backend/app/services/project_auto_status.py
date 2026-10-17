"""Auto-transition helpers for Project status.

Centralised so that any code path that records work against a project
can bump its status without duplicating logic.

Currently exposes:

- ``bump_to_in_progress_if_needed(db, project_id)`` — used by punch
  creation paths. If the referenced project is not yet
  ``IN_PROGRESS`` and not ``DELIVERED``, switches it to
  ``IN_PROGRESS``. Acts on the SQLAlchemy session passed in (no
  commit) so callers control the transaction.
- ``archive_soumission_on_delivery`` / ``unarchive_soumission_on_reopen``
  — projet terminé (livré) → sa soumission passe dans la colonne
  « Terminées » du tableau des soumissions ; projet rouvert → elle
  revient dans la colonne de son statut.
- ``archive_soumissions_of_delivered_projects_once`` — rattrapage au
  démarrage, une seule fois, des soumissions dont le projet était déjà
  livré.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, exists, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectStatus
from app.models.soumission import Soumission

log = logging.getLogger(__name__)

#: Marqueur applied_backfills du rattrapage des soumissions dont le projet
#: était déjà livré (Steven, 2026-10-17).
CLE_RATTRAPAGE_SOUMISSIONS_TERMINEES = "soumission_terminee_projet_livre_v1"


async def bump_to_in_progress_if_needed(
    db: AsyncSession, project_id: Optional[int]
) -> None:
    """Promote ``project`` to IN_PROGRESS unless it already is, or it's
    already DELIVERED (we don't resurrect closed chantiers).

    Idempotent and safe to call from any punch-creation path.
    """
    if project_id is None:
        return
    project = (
        await db.execute(
            select(Project).where(Project.id == project_id)
        )
    ).scalar_one_or_none()
    if project is None:
        return
    if project.status in (
        ProjectStatus.IN_PROGRESS.value,
        ProjectStatus.DELIVERED.value,
    ):
        return
    project.status = ProjectStatus.IN_PROGRESS.value


def _tous_ses_projets_livres(soumission_id):
    """Condition SQL : la soumission a au moins un projet et TOUS ses
    projets sont livrés. Une soumission reliée à plusieurs projets n'est
    terminée qu'à la livraison du dernier."""
    return and_(
        exists().where(Project.soumission_id == soumission_id),
        ~exists().where(
            Project.soumission_id == soumission_id,
            Project.status != ProjectStatus.DELIVERED.value,
        ),
    )


def _colonne(archived_at: Optional[datetime]) -> dict:
    """Valeurs d'un changement de colonne. ``updated_at`` reste tel quel :
    changer de colonne ne modifie pas la soumission, et le tableau de bord
    date par ``updated_at`` les ventes acceptées sans ``accepted_at``."""
    return {"archived_at": archived_at, "updated_at": Soumission.updated_at}


async def _soumission_du_projet(
    db: AsyncSession, project_id: Optional[int]
) -> Optional[int]:
    if project_id is None:
        return None
    # La condition SQL lit le statut en base : les changements en attente
    # (statut, lien soumission) doivent y être.
    await db.flush()
    return (
        await db.execute(
            select(Project.soumission_id).where(Project.id == project_id)
        )
    ).scalar_one_or_none()


async def archive_soumission_on_delivery(
    db: AsyncSession, project_id: Optional[int]
) -> None:
    """Quand un projet passe « livré » (terminé), sa soumission liée passe
    dans la colonne « Terminées » du tableau (drapeau ``archived_at``),
    dès que TOUS les projets reliés à cette soumission sont livrés.
    Idempotent : ne touche pas une soumission déjà terminée. À appeler
    sur la TRANSITION vers livré (édition projet, solde de la facture
    finale) ou quand un projet déjà livré est relié à une soumission.
    """
    soumission_id = await _soumission_du_projet(db, project_id)
    if not soumission_id:
        return
    try:
        async with db.begin_nested():
            await db.execute(
                update(Soumission)
                .where(
                    Soumission.id == soumission_id,
                    Soumission.archived_at.is_(None),
                    _tous_ses_projets_livres(soumission_id),
                )
                .values(**_colonne(datetime.now(timezone.utc)))
            )
    except Exception as exc:  # noqa: BLE001
        # Effet secondaire : ne jamais casser la livraison du projet.
        log.warning(
            "Soumission %s du projet %s non passée dans « Terminées » : %s",
            soumission_id,
            project_id,
            exc,
        )


async def unarchive_soumission_on_reopen(
    db: AsyncSession, project_id: Optional[int]
) -> None:
    """Projet sorti de « livré » (rouvert, correction…) : sa soumission
    quitte « Terminées » et revient dans la colonne de son statut
    (Acceptées). À appeler sur la TRANSITION livré → autre statut.
    """
    soumission_id = await _soumission_du_projet(db, project_id)
    if not soumission_id:
        return
    try:
        async with db.begin_nested():
            await db.execute(
                update(Soumission)
                .where(
                    Soumission.id == soumission_id,
                    Soumission.archived_at.is_not(None),
                )
                .values(**_colonne(None))
            )
    except Exception as exc:  # noqa: BLE001
        # Effet secondaire : ne jamais bloquer le changement de statut.
        log.warning(
            "Soumission %s du projet rouvert %s non ressortie de "
            "« Terminées » : %s",
            soumission_id,
            project_id,
            exc,
        )


async def archive_soumissions_of_delivered_projects_once(
    db: AsyncSession,
) -> int:
    """Rattrapage, une seule fois (marqueur applied_backfills) : toute
    soumission dont les projets sont tous déjà livrés passe dans
    « Terminées ». Une soumission ressortie ensuite à la main n'y est
    jamais remise. Commite ; retourne le nombre de soumissions
    déplacées."""
    deja = (
        await db.execute(
            text("SELECT 1 FROM applied_backfills WHERE key = :k"),
            {"k": CLE_RATTRAPAGE_SOUMISSIONS_TERMINEES},
        )
    ).first()
    if deja is not None:
        return 0
    res = await db.execute(
        update(Soumission)
        .where(
            Soumission.archived_at.is_(None),
            _tous_ses_projets_livres(Soumission.id),
        )
        .values(**_colonne(datetime.now(timezone.utc)))
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        text(
            "INSERT INTO applied_backfills (key) VALUES (:k) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"k": CLE_RATTRAPAGE_SOUMISSIONS_TERMINEES},
    )
    await db.commit()
    return res.rowcount or 0
