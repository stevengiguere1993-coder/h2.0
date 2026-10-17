"""Auto-transition helpers for Project status.

Centralised so that any code path that records work against a project
can bump its status without duplicating logic.

Currently exposes:

- ``bump_to_in_progress_if_needed(db, project_id)`` — used by punch
  creation paths. If the referenced project is not yet
  ``IN_PROGRESS`` and not ``DELIVERED``, switches it to
  ``IN_PROGRESS``. Acts on the SQLAlchemy session passed in (no
  commit) so callers control the transaction.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectStatus


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


async def archive_soumission_on_delivery(
    db: AsyncSession, project_id: Optional[int]
) -> None:
    """Quand un projet passe « livré », on archive sa soumission liée (elle
    rejoint la colonne « Archivée » du tableau). Idempotent : ne touche pas
    une soumission déjà archivée. À appeler sur la TRANSITION vers livré
    (depuis l'édition projet ET depuis le solde de la facture finale).
    """
    if project_id is None:
        return
    from datetime import datetime, timezone

    from sqlalchemy import update as _update
    from app.models.soumission import Soumission

    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None or not project.soumission_id:
        return
    try:
        async with db.begin_nested():
            sm_id = (
                await db.execute(
                    select(Soumission.id).where(
                        Soumission.id == project.soumission_id,
                        Soumission.archived_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if sm_id is not None:
                await db.execute(
                    _update(Soumission)
                    .where(Soumission.id == sm_id)
                    .values(archived_at=datetime.now(timezone.utc))
                )
    except Exception:  # noqa: BLE001
        # Effet secondaire : ne jamais casser la livraison du projet.
        pass
