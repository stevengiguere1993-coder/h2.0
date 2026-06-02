"""Seeder idempotent des règles d'auto-upload Drive — Phase 6.

Appelé au boot du backend (cf. ``app.main.lifespan``). Crée 5 règles
``DriveAutoUpload`` typiques pour les workflows Phil, **toutes inactives
par défaut**. Phil les active depuis ``/parametres/drive`` après avoir
vérifié les sous-dossiers / noms de fichiers.

Règles par défaut :

1. fiche_analyse      → ProspectionDeal | racine        | "Fiche d'analyse.pdf"        | overwrite
2. offre_pptx         → ProspectionDeal | "Dossier investisseur" | "Offre_{date}.pptx"   | version
3. nda_signed         → ProspectionDeal | "Dossier investisseur" | "NDA_{nom_signataire}_signé.pdf" | keep_both
4. soumission_pdf     → DevlogClient     | "Soumissions" | "Soumission_{numero}.pdf"     | overwrite
5. facture_pdf        → DevlogClient     | "Factures"    | "Facture_{numero}.pdf"        | overwrite

Idempotence : on vérifie l'existence par couple
``(document_type, entity_type)`` avant insert. Si la règle existe déjà
(peu importe ses valeurs), on ne touche à rien — Phil aura peut-être
customisé sa version.

Échecs silencieux : si la table n'existe pas encore (premier boot avant
migration) ou si une autre exception survient, on logge un warning et on
continue le startup normalement. Le seeder n'est jamais critique.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_auto_upload import DriveAutoUpload

log = logging.getLogger(__name__)


# Source de vérité des règles par défaut. Modifier ici si Phil demande à
# changer les sous-dossiers ou les noms — le seeder ne recrée pas une
# règle déjà existante par ``(document_type, entity_type)``.
_DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "name": "Fiche d'analyse → Deal",
        "document_type": "fiche_analyse",
        "entity_type": "ProspectionDeal",
        "subfolder_path_template": "",  # racine du dossier du deal
        "file_name_template": "Fiche d'analyse.pdf",
        "overwrite_strategy": "overwrite",
        "active": False,
        "description": (
            "Dépose la fiche d'analyse PDF à la racine du dossier Drive "
            "du deal. Écrase la version précédente (un seul fichier à jour)."
        ),
    },
    {
        "name": "Offre d'investissement (PPTX) → Deal",
        "document_type": "offre_pptx",
        "entity_type": "ProspectionDeal",
        "subfolder_path_template": "Dossier investisseur",
        "file_name_template": "Offre_{date}.pptx",
        "overwrite_strategy": "version",
        "active": False,
        "description": (
            "Dépose l'offre PPTX dans le sous-dossier « Dossier "
            "investisseur ». Conserve l'historique (suffixe daté)."
        ),
    },
    {
        "name": "NDA signé → Deal",
        "document_type": "nda_signed",
        "entity_type": "ProspectionDeal",
        "subfolder_path_template": "Dossier investisseur",
        "file_name_template": "NDA_{nom_signataire}_signé.pdf",
        "overwrite_strategy": "keep_both",
        "active": False,
        "description": (
            "Dépose le NDA signé dans « Dossier investisseur ». Garde "
            "chaque signataire (un investisseur = un fichier)."
        ),
    },
    {
        "name": "Soumission → Client Dev Log",
        "document_type": "soumission_pdf",
        "entity_type": "DevlogClient",
        "subfolder_path_template": "Soumissions",
        "file_name_template": "Soumission_{numero}.pdf",
        "overwrite_strategy": "overwrite",
        "active": False,
        "description": (
            "Dépose la soumission PDF dans le sous-dossier « Soumissions » "
            "du client. Écrase la version précédente du même numéro."
        ),
    },
    {
        "name": "Facture → Client Dev Log",
        "document_type": "facture_pdf",
        "entity_type": "DevlogClient",
        "subfolder_path_template": "Factures",
        "file_name_template": "Facture_{numero}.pdf",
        "overwrite_strategy": "overwrite",
        "active": False,
        "description": (
            "Dépose la facture PDF dans le sous-dossier « Factures » du "
            "client. Écrase la version précédente du même numéro."
        ),
    },
]


async def seed_default_drive_auto_uploads(db: AsyncSession) -> int:
    """Crée les règles d'auto-upload absentes. Retourne le nombre créé.

    Best-effort : capture toutes les exceptions et logge un warning, pour
    ne jamais bloquer le boot.
    """
    created = 0
    try:
        for spec in _DEFAULT_RULES:
            stmt = select(DriveAutoUpload).where(
                DriveAutoUpload.document_type == spec["document_type"],
                DriveAutoUpload.entity_type == spec["entity_type"],
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                continue
            rule = DriveAutoUpload(**spec)
            db.add(rule)
            created += 1
        if created:
            await db.commit()
            log.info(
                "drive_auto_uploads seed: %d regle(s) creee(s) par defaut",
                created,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("drive_auto_uploads seed failed: %s", exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
    return created


__all__ = ["seed_default_drive_auto_uploads"]
