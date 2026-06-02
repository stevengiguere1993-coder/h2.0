"""Seeder idempotent des Drive Page Modules — Phase 7.

Appelé au boot du backend (cf. ``app.main.lifespan``). Maintient une
ligne ``DrivePageModule`` par type d'entité connu (cf. ``_REGISTRY``).
Phil active ensuite chaque type via la page ``/parametres/drive``
(section "Afficher Drive sur les pages", navigation par pôle).

Deux comportements selon que la ligne existe déjà :

- **Absente** → on la crée *inactive* (``active=False``) avec ses
  métadonnées (``pole`` / ``label`` / ``route``) et un ``display_title``
  par défaut ("Documents Drive").
- **Existante** → on *upsert les métadonnées seulement* (``pole`` /
  ``label`` / ``route`` / ``display_order``). On ne touche JAMAIS à
  ``active`` ni ``display_title`` : Phil les a peut-être déjà
  configurés. Ce upsert garde le registry à jour (libellés / routes
  affinés) sans écraser la configuration utilisateur.

``_REGISTRY`` est la SOURCE DE VÉRITÉ des ``entity_type`` : un autre
agent câble ``<EntityDriveSection entityType="..." />`` sur les pages
avec EXACTEMENT ces noms. Ne pas renommer un ``entity_type`` existant.

Échecs silencieux : si la table n'existe pas encore (premier boot) ou
qu'une autre exception survient, on logge un warning et on continue le
startup. Le seeder n'est jamais critique.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_page_module import DrivePageModule

log = logging.getLogger(__name__)


# Pôles métier — alimentent les onglets de la navigation Settings.
POLE_PROSPECTION = "Prospection"
POLE_DEVLOG = "Développement logiciel"
POLE_CONSTRUCTION = "Construction"
POLE_ENTREPRISES = "Gestion d'entreprises"
POLE_IMMOBILIER = "Gestion immobilière"


# Registry complet des pages d'entité câblables. L'ordre = display_order
# (regroupé par pôle pour une lecture naturelle). Chaque ``entity_type``
# est la SOURCE DE VÉRITÉ : le composant <EntityDriveSection> est câblé
# côté pages avec exactement ces noms. Pour câbler une nouvelle page :
# ajouter une entrée ici (cf. docs/DRIVE_INTEGRATION.md).
_REGISTRY: list[dict[str, Any]] = [
    # --- Prospection -------------------------------------------------
    {
        "entity_type": "ProspectionDeal",
        "pole": POLE_PROSPECTION,
        "label": "Deal Pipeline",
        "route": "/prospection/pipeline/[id]",
    },
    {
        "entity_type": "ProspectionLead",
        "pole": POLE_PROSPECTION,
        "label": "Lead",
        "route": "/prospection/[id]",
    },
    # --- Développement logiciel --------------------------------------
    {
        "entity_type": "DevlogClient",
        "pole": POLE_DEVLOG,
        "label": "Client",
        "route": "/dev-logiciel/clients/[id]",
    },
    {
        "entity_type": "DevlogProject",
        "pole": POLE_DEVLOG,
        "label": "Projet",
        "route": "/dev-logiciel/projets/[id]",
    },
    {
        "entity_type": "DevlogSoumission",
        "pole": POLE_DEVLOG,
        "label": "Soumission",
        "route": "/dev-logiciel/soumissions/[id]",
    },
    {
        "entity_type": "DevlogContract",
        "pole": POLE_DEVLOG,
        "label": "Contrat",
        "route": "/dev-logiciel/contrats/[id]",
    },
    {
        "entity_type": "DevlogLead",
        "pole": POLE_DEVLOG,
        "label": "Lead",
        "route": "/dev-logiciel/leads/[id]",
    },
    {
        "entity_type": "DevlogInvoice",
        "pole": POLE_DEVLOG,
        "label": "Facture",
        "route": "/dev-logiciel/facturation/[id]",
    },
    # --- Construction ------------------------------------------------
    {
        "entity_type": "ConstructionProject",
        "pole": POLE_CONSTRUCTION,
        "label": "Projet",
        "route": "/app/projets/[id]",
    },
    {
        "entity_type": "ConstructionClient",
        "pole": POLE_CONSTRUCTION,
        "label": "Client",
        "route": "/app/clients/[id]",
    },
    {
        "entity_type": "ConstructionSoumission",
        "pole": POLE_CONSTRUCTION,
        "label": "Soumission",
        "route": "/app/soumissions/[id]",
    },
    {
        "entity_type": "ConstructionFacture",
        "pole": POLE_CONSTRUCTION,
        "label": "Facture",
        "route": "/app/facturation/[id]",
    },
    {
        "entity_type": "BonTravail",
        "pole": POLE_CONSTRUCTION,
        "label": "Bon de travail",
        "route": "/app/bons/[id]",
    },
    {
        "entity_type": "PurchaseOrder",
        "pole": POLE_CONSTRUCTION,
        "label": "Bon de commande",
        "route": "/app/po/[id]",
    },
    {
        "entity_type": "Achat",
        "pole": POLE_CONSTRUCTION,
        "label": "Achat / dépense",
        "route": "/app/achats/[id]",
    },
    {
        "entity_type": "SousTraitant",
        "pole": POLE_CONSTRUCTION,
        "label": "Sous-traitant",
        "route": "/app/sous-traitants/[id]",
    },
    {
        "entity_type": "Fournisseur",
        "pole": POLE_CONSTRUCTION,
        "label": "Fournisseur",
        "route": "/app/fournisseurs/[id]",
    },
    {
        "entity_type": "Employe",
        "pole": POLE_CONSTRUCTION,
        "label": "Employé",
        "route": "/app/employes/[id]",
    },
    {
        "entity_type": "ContactRequest",
        "pole": POLE_CONSTRUCTION,
        "label": "Prospect CRM",
        "route": "/app/crm/[id]",
    },
    # --- Gestion d'entreprises ---------------------------------------
    {
        "entity_type": "Entreprise",
        "pole": POLE_ENTREPRISES,
        "label": "Entreprise",
        "route": "/entreprises/[id]",
    },
    {
        "entity_type": "Rencontre",
        "pole": POLE_ENTREPRISES,
        "label": "Rencontre",
        "route": "/entreprises/rencontres/[id]",
    },
    # --- Gestion immobilière -----------------------------------------
    {
        "entity_type": "Immeuble",
        "pole": POLE_IMMOBILIER,
        "label": "Immeuble",
        "route": "/immobilier/immeubles/[id]",
    },
]


async def seed_default_drive_page_modules(db: AsyncSession) -> int:
    """Synchronise la table avec ``_REGISTRY``. Retourne le nombre créé.

    - Crée les lignes absentes (inactives, titre par défaut).
    - Upsert les métadonnées (``pole`` / ``label`` / ``route`` /
      ``display_order``) des lignes existantes, sans toucher ``active``
      ni ``display_title`` (config utilisateur préservée).

    Best-effort : capture toutes les exceptions et logge un warning,
    pour ne jamais bloquer le boot.
    """
    created = 0
    updated = 0
    try:
        for order, spec in enumerate(_REGISTRY):
            stmt = select(DrivePageModule).where(
                DrivePageModule.entity_type == spec["entity_type"]
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing is None:
                module = DrivePageModule(
                    entity_type=spec["entity_type"],
                    active=False,
                    display_title="Documents Drive",
                    display_order=order,
                    pole=spec["pole"],
                    label=spec["label"],
                    route=spec["route"],
                )
                db.add(module)
                created += 1
                continue

            # Upsert metadata uniquement — on ne touche pas à active /
            # display_title (Phil les a peut-être déjà configurés).
            changed = False
            if existing.pole != spec["pole"]:
                existing.pole = spec["pole"]
                changed = True
            if existing.label != spec["label"]:
                existing.label = spec["label"]
                changed = True
            if existing.route != spec["route"]:
                existing.route = spec["route"]
                changed = True
            if existing.display_order != order:
                existing.display_order = order
                changed = True
            if changed:
                updated += 1

        if created or updated:
            await db.commit()
            log.info(
                "drive_page_modules seed: %d cree(s), %d metadata maj",
                created,
                updated,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("drive_page_modules seed failed: %s", exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
    return created


__all__ = ["seed_default_drive_page_modules"]
