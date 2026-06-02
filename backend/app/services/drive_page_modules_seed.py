"""Seeder idempotent des Drive Page Modules — Phase 7.

Appelé au boot du backend (cf. ``app.main.lifespan``). Crée une ligne
``DrivePageModule`` **inactive** par type d'entité connu, si elle
n'existe pas déjà. Phil active ensuite chaque type via la page
``/parametres/drive`` (section "Sections Drive par page").

Idempotence : on vérifie l'existence par ``entity_type`` avant insert.
Si la ligne existe (peu importe son état actif/titre), on ne touche à
rien — Phil a peut-être déjà activé et personnalisé le titre.

Échecs silencieux : si la table n'existe pas encore (premier boot) ou
qu'une autre exception survient, on logge un warning et on continue le
startup. Le seeder n'est jamais critique.

``display_title`` par défaut = NULL ; le composant ``<EntityDriveSection>``
affiche alors "Documents Drive". On pré-remplit néanmoins un titre
parlant par type pour que le tableau Settings soit lisible d'emblée.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_page_module import DrivePageModule

log = logging.getLogger(__name__)


# Source de vérité des types de pages câblables. L'ordre = display_order
# (priorité business : prospection deals d'abord, puis devlog, puis
# construction/lead/entreprise). Modifier ici pour câbler un nouveau
# type (cf. docs/DRIVE_INTEGRATION.md, section "Câbler une page").
_DEFAULT_MODULES: list[dict[str, Any]] = [
    {"entity_type": "ProspectionDeal", "display_title": "Documents Drive"},
    {"entity_type": "DevlogClient", "display_title": "Documents Drive"},
    {"entity_type": "DevlogProject", "display_title": "Documents Drive"},
    {"entity_type": "DevlogSoumission", "display_title": "Documents Drive"},
    {"entity_type": "DevlogContract", "display_title": "Documents Drive"},
    {"entity_type": "ConstructionProject", "display_title": "Documents Drive"},
    {"entity_type": "ProspectionLead", "display_title": "Documents Drive"},
    {"entity_type": "Entreprise", "display_title": "Documents Drive"},
]


async def seed_default_drive_page_modules(db: AsyncSession) -> int:
    """Crée les modules par défaut absents. Retourne le nombre créé.

    Best-effort : capture toutes les exceptions et logge un warning,
    pour ne jamais bloquer le boot.
    """
    created = 0
    try:
        for order, spec in enumerate(_DEFAULT_MODULES):
            stmt = select(DrivePageModule).where(
                DrivePageModule.entity_type == spec["entity_type"]
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                continue
            module = DrivePageModule(
                entity_type=spec["entity_type"],
                active=False,
                display_title=spec.get("display_title"),
                display_order=order,
            )
            db.add(module)
            created += 1
        if created:
            await db.commit()
            log.info(
                "drive_page_modules seed: %d module(s) cree(s) par defaut",
                created,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("drive_page_modules seed failed: %s", exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
    return created


__all__ = ["seed_default_drive_page_modules"]
