"""Seeder idempotent des Drive Conventions par défaut — Phase 4.

Appelé au boot du backend (cf. ``app.main.lifespan``). Crée 4 conventions
typiques pour les workflows Phil :

1. Deal Pipeline → 0 - En cours
2. Nouveau client Dev Log → Clients Dev
3. Nouveau projet Dev Log
4. Nouveau projet Construction

Toutes sont créées **inactives** par défaut. Phil doit :

1. Configurer le ``parent_folder_drive_id`` (vide à la création) via
   la modal d'édition.
2. Activer la convention via le toggle.

Idempotence : on vérifie l'existence par couple ``(name, entity_type)``
avant insert. Si la convention existe déjà (peu importe ses valeurs),
on ne touche à rien — Phil aura peut-être customisé sa version.

Échecs silencieux : si la table n'existe pas encore (cas premier boot
avant migration) ou si une autre exception survient, on logge un
warning et on continue le startup normalement. Le seeder n'est jamais
critique.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_convention import DriveConvention

log = logging.getLogger(__name__)


# Source de vérité des conventions par défaut. Modifier ici si Phil
# demande à changer les noms ou les sous-dossiers — le seeder ne
# recrée pas une convention déjà existante par ``(name, entity_type)``.
_DEFAULT_CONVENTIONS: list[dict[str, Any]] = [
    {
        "name": "Deal Pipeline → 0 - En cours",
        "entity_type": "ProspectionDeal",
        "trigger_event": "created",  # informatif Phase 4 (pas de hook auto)
        "parent_folder_drive_id": None,  # à configurer par Phil
        "folder_name_template": "{address}, {city}",
        "subfolders_to_create": [
            "Photos",
            "Soumissions",
            "Financement",
            "Baux",
            "Dépenses",
        ],
        "active": False,
        "priority": 100,
        "description": (
            "Convention par défaut pour les deals de prospection. "
            "À activer après configuration du dossier parent Drive."
        ),
    },
    {
        "name": "Nouveau client Dev Log → Clients Dev",
        "entity_type": "DevlogClient",
        "trigger_event": "created",
        "parent_folder_drive_id": None,
        "folder_name_template": "{nom_client}",
        "subfolders_to_create": [
            "Soumissions",
            "Contrats",
            "Factures",
            "Projets",
        ],
        "active": False,
        "priority": 100,
        "description": (
            "Convention par défaut pour les clients Dev Logiciel. "
            "À activer après configuration du dossier parent Drive."
        ),
    },
    {
        "name": "Nouveau projet Dev Log",
        "entity_type": "DevlogProject",
        "trigger_event": "created",
        "parent_folder_drive_id": None,
        "folder_name_template": "{nom_projet} ({nom_client})",
        "subfolders_to_create": [
            "Documents",
            "Captures",
            "Achats",
        ],
        "active": False,
        "priority": 100,
        "description": (
            "Convention par défaut pour les projets Dev Logiciel. "
            "À activer après configuration du dossier parent Drive."
        ),
    },
    {
        "name": "Nouveau projet Construction",
        "entity_type": "ConstructionProject",
        "trigger_event": "created",
        "parent_folder_drive_id": None,
        "folder_name_template": "{address}",
        "subfolders_to_create": [
            "Photos chantier",
            "Reçus",
            "Documents",
            "Plans",
        ],
        "active": False,
        "priority": 100,
        "description": (
            "Convention par défaut pour les projets Construction. "
            "À activer après configuration du dossier parent Drive."
        ),
    },
]


async def seed_default_drive_conventions(db: AsyncSession) -> int:
    """Crée les conventions par défaut absentes. Retourne le nombre créé.

    Best-effort : capture toutes les exceptions et logge un warning,
    pour ne jamais bloquer le boot.
    """
    created = 0
    try:
        for spec in _DEFAULT_CONVENTIONS:
            stmt = select(DriveConvention).where(
                DriveConvention.name == spec["name"],
                DriveConvention.entity_type == spec["entity_type"],
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                continue
            convention = DriveConvention(**spec)
            db.add(convention)
            created += 1
        if created:
            await db.commit()
            log.info(
                "drive_conventions seed: %d convention(s) creee(s) par defaut",
                created,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("drive_conventions seed failed: %s", exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
    return created


__all__ = ["seed_default_drive_conventions"]
