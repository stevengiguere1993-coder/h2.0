"""Moteur d'exécution des Drive Conventions — Phase 4.

Une "Drive Convention" (cf. modèle :class:`app.models.drive_convention.DriveConvention`)
est une règle configurable qui dit COMMENT et OÙ créer un dossier
Drive pour une entité Kratos donnée (deal, projet, client, etc.).

Ce module implémente le moteur d'application des conventions :

- :func:`apply_convention_to_entity` — applique manuellement une
  convention à une entité existante. Crée le dossier Drive, copie
  un template optionnel, crée les sous-dossiers, et persiste un
  :class:`DriveEntityLink` pour que la page entité affiche le bon
  dossier dans :class:`DriveFolderExplorer`.

- :func:`resolve_folder_name` — résout un template de nom avec les
  variables disponibles pour le type d'entité (ex. ``{address}``,
  ``{city}``). Les variables manquantes sont laissées telles quelles
  avec un warning, jamais une crash.

- :func:`get_supported_entity_types` — métadonnées des types d'entités
  supportés et de leurs variables disponibles, utilisé par l'UI pour
  populer les dropdowns du wizard de création de convention.

Phase 4 ne déclenche AUCUN hook automatique (pas d'event listener
SQLAlchemy "à la création de l'entité, appliquer la convention X").
Cette responsabilité est reportée à la Phase 5. Pour l'instant on
applique uniquement via l'endpoint ``POST /api/v1/drive/conventions/{id}/apply``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_convention import DriveConvention
from app.models.drive_entity_link import DriveEntityLink
from app.services import drive_api

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions custom
# ---------------------------------------------------------------------------


class ConventionEngineError(Exception):
    """Erreur générique du moteur de conventions."""


class ConventionNotFound(ConventionEngineError):
    """La convention demandée n'existe pas (ou est inactive si filtrée)."""


class EntityNotFound(ConventionEngineError):
    """L'entité Kratos cible n'existe pas."""


class EntityAlreadyLinked(ConventionEngineError):
    """Un :class:`DriveEntityLink` existe déjà pour cette entité.

    Le moteur refuse de créer un second lien pour éviter qu'une même
    entité pointe vers deux dossiers Drive différents (ambiguïté côté
    UI explorer). Phil doit d'abord supprimer le lien existant via
    ``DELETE /api/v1/drive/entity-links/{id}`` puis réessayer.
    """


class UnsupportedEntityType(ConventionEngineError):
    """Type d'entité inconnu du registry — la convention ne peut pas
    extraire les variables nécessaires au template de nommage."""


class ConventionMisconfigured(ConventionEngineError):
    """La convention manque d'un champ obligatoire (parent_folder_drive_id,
    folder_name_template, etc.) pour pouvoir être appliquée."""


# ---------------------------------------------------------------------------
# Registry des types d'entités supportés
# ---------------------------------------------------------------------------
#
# Chaque entrée déclare :
# - ``label`` : libellé UI français.
# - ``model_path`` : chemin du module + nom de classe SQLAlchemy
#   (chargement paresseux pour éviter les imports circulaires si le
#   modèle référence indirectement le service ; pas critique
#   actuellement, mais sécurise les évolutions).
# - ``variables`` : liste de dicts ``{key, label, description}`` —
#   alimente l'UI du wizard pour montrer les placeholders disponibles
#   et leur sémantique.
# - ``extract`` : callable async qui prend ``(entity, db)`` et retourne
#   un dict ``{var_name: str}`` prêt à interpoler.
#
# L'ordre suit la priorité business de Phil : prospection deals d'abord
# (cas le plus fréquent), puis devlog, puis construction.


def _fmt_date(dt: Any) -> str:
    """Formatte un datetime/date en ``YYYY-MM-DD``. Retourne "" si None."""
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        return dt.date().isoformat()
    try:
        return dt.isoformat()  # date object
    except Exception:  # noqa: BLE001
        return str(dt)


async def _extract_prospection_deal(entity: Any, db: AsyncSession) -> dict[str, str]:
    # ProspectionDeal a un ``address`` direct ; city/postal_code vivent
    # sur le ProspectionLead lié via lead_analysis (chain transitive).
    # Pour MVP : on offre {address} qui marche toujours, et
    # {city}/{postal_code} via le lead_analysis si disponible.
    # Fallback : "" si pas trouvable.
    city = ""
    postal_code = ""
    try:
        la = getattr(entity, "lead_analysis", None)
        if la is not None:
            # LeadAnalysis -> lead -> city/postal_code (best-effort).
            lead = getattr(la, "lead", None) or getattr(la, "prospection_lead", None)
            if lead is not None:
                city = getattr(lead, "city", "") or ""
                postal_code = getattr(lead, "postal_code", "") or ""
    except Exception:  # noqa: BLE001
        pass
    return {
        "address": getattr(entity, "address", "") or "",
        "city": city,
        "postal_code": postal_code,
        "date_creation": _fmt_date(getattr(entity, "created_at", None)),
    }


async def _extract_devlog_project(entity: Any, db: AsyncSession) -> dict[str, str]:
    nom_client = ""
    client_id = getattr(entity, "client_id", None)
    if client_id is not None:
        from app.models.devlog_client import DevlogClient

        client = await db.get(DevlogClient, client_id)
        if client is not None:
            nom_client = getattr(client, "name", "") or ""
    return {
        "nom_projet": getattr(entity, "name", "") or "",
        "nom_client": nom_client,
        "date_creation": _fmt_date(getattr(entity, "created_at", None)),
    }


async def _extract_devlog_client(entity: Any, db: AsyncSession) -> dict[str, str]:
    return {
        "nom_client": getattr(entity, "name", "") or "",
        "date_creation": _fmt_date(getattr(entity, "created_at", None)),
    }


async def _extract_prospection_lead(entity: Any, db: AsyncSession) -> dict[str, str]:
    return {
        "address": getattr(entity, "address", "") or "",
        "city": getattr(entity, "city", "") or "",
        "date_creation": _fmt_date(getattr(entity, "created_at", None)),
    }


async def _extract_construction_project(entity: Any, db: AsyncSession) -> dict[str, str]:
    return {
        "address": getattr(entity, "address", "") or "",
        "nom_projet": getattr(entity, "name", "") or "",
        "date_creation": _fmt_date(getattr(entity, "created_at", None)),
    }


# Registry des types d'entités. ``model_path`` est une tuple
# ``(module_path, class_name)`` — résolu paresseusement via importlib
# pour éviter les imports en tête de module.
_ENTITY_REGISTRY: dict[str, dict[str, Any]] = {
    "ProspectionDeal": {
        "label": "Deal Pipeline (Prospection)",
        "model_path": ("app.models.prospection_deal", "ProspectionDeal"),
        "variables": [
            {"key": "address", "label": "Adresse", "description": "Adresse du deal (ex. 1660 Saint-Clément)."},
            {"key": "city", "label": "Ville", "description": "Ville si disponible via le lead lié."},
            {"key": "postal_code", "label": "Code postal", "description": "Code postal si disponible via le lead lié."},
            {"key": "date_creation", "label": "Date de création", "description": "Format YYYY-MM-DD."},
        ],
        "extract": _extract_prospection_deal,
    },
    "DevlogProject": {
        "label": "Projet Dev Logiciel",
        "model_path": ("app.models.devlog_project", "DevlogProject"),
        "variables": [
            {"key": "nom_projet", "label": "Nom du projet", "description": "Champ ``name`` du projet."},
            {"key": "nom_client", "label": "Nom du client", "description": "Nom du DevlogClient lié."},
            {"key": "date_creation", "label": "Date de création", "description": "Format YYYY-MM-DD."},
        ],
        "extract": _extract_devlog_project,
    },
    "DevlogClient": {
        "label": "Client Dev Logiciel",
        "model_path": ("app.models.devlog_client", "DevlogClient"),
        "variables": [
            {"key": "nom_client", "label": "Nom du client", "description": "Champ ``name`` du client."},
            {"key": "date_creation", "label": "Date de création", "description": "Format YYYY-MM-DD."},
        ],
        "extract": _extract_devlog_client,
    },
    "ProspectionLead": {
        "label": "Lead Prospection",
        "model_path": ("app.models.prospection_lead", "ProspectionLead"),
        "variables": [
            {"key": "address", "label": "Adresse", "description": "Adresse du lead."},
            {"key": "city", "label": "Ville", "description": "Ville du lead."},
            {"key": "date_creation", "label": "Date de création", "description": "Format YYYY-MM-DD."},
        ],
        "extract": _extract_prospection_lead,
    },
    "ConstructionProject": {
        "label": "Projet Construction",
        "model_path": ("app.models.project", "Project"),
        "variables": [
            {"key": "address", "label": "Adresse", "description": "Adresse du chantier."},
            {"key": "nom_projet", "label": "Nom du projet", "description": "Champ ``name`` du projet."},
            {"key": "date_creation", "label": "Date de création", "description": "Format YYYY-MM-DD."},
        ],
        "extract": _extract_construction_project,
    },
}


async def get_supported_entity_types() -> list[dict[str, Any]]:
    """Métadonnées pour les dropdowns du wizard frontend.

    Format de retour pour chaque entrée ::

        {
            "key": "ProspectionDeal",
            "label": "Deal Pipeline (Prospection)",
            "variables": [
                {"key": "address", "label": "Adresse", "description": "..."},
                ...
            ]
        }
    """
    return [
        {
            "key": key,
            "label": entry["label"],
            "variables": entry["variables"],
        }
        for key, entry in _ENTITY_REGISTRY.items()
    ]


# ---------------------------------------------------------------------------
# Chargement d'une entité Kratos par (type, id)
# ---------------------------------------------------------------------------


async def _load_entity(
    entity_type: str, entity_id: int, db: AsyncSession
) -> Any:
    if entity_type not in _ENTITY_REGISTRY:
        raise UnsupportedEntityType(
            f"Type d'entité non supporté par les conventions : {entity_type}. "
            f"Types supportés : {', '.join(_ENTITY_REGISTRY)}."
        )
    module_path, class_name = _ENTITY_REGISTRY[entity_type]["model_path"]
    import importlib

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    entity = await db.get(cls, entity_id)
    if entity is None:
        raise EntityNotFound(
            f"{entity_type} #{entity_id} introuvable en base."
        )
    return entity


# ---------------------------------------------------------------------------
# Résolution du template de nom
# ---------------------------------------------------------------------------


_TEMPLATE_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


async def resolve_folder_name(
    template: str,
    entity_type: str,
    entity_id: int,
    db: AsyncSession,
) -> str:
    """Résout ``template`` avec les variables disponibles pour ce type.

    Variables manquantes (clé absente du registry ou valeur vide) : on
    laisse le placeholder ``{var}`` tel quel + on logge un warning. Ne
    crash pas — l'UI affichera un nom partiellement résolu, à Phil de
    corriger sa convention.

    Espaces superflus dûs à des variables vides : nettoyés à la marge
    (séquences ``,  ,``, ``  ``) pour des noms propres.
    """
    if not template:
        raise ConventionMisconfigured(
            "Le template de nom de la convention est vide."
        )

    entry = _ENTITY_REGISTRY.get(entity_type)
    if entry is None:
        raise UnsupportedEntityType(
            f"Type d'entité non supporté par les conventions : {entity_type}."
        )

    entity = await _load_entity(entity_type, entity_id, db)
    variables = await entry["extract"](entity, db)

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in variables and variables[key]:
            return str(variables[key])
        log.warning(
            "drive_conventions: placeholder '{%s}' non resolu pour %s#%s "
            "(template=%r)",
            key,
            entity_type,
            entity_id,
            template,
        )
        # Variable absente ou vide → on laisse le placeholder tel quel.
        return match.group(0)

    resolved = _TEMPLATE_VAR_RE.sub(_replace, template)

    # Nettoyage léger : si une variable vide a laissé "X, , Y" → "X, Y".
    resolved = re.sub(r",\s*,", ",", resolved)
    resolved = re.sub(r"\s{2,}", " ", resolved)
    resolved = resolved.strip(" ,")

    if not resolved:
        # Cas pathologique : tout le template était constitué de
        # placeholders vides.
        raise ConventionMisconfigured(
            f"Template {template!r} a résolu à une chaîne vide pour "
            f"{entity_type}#{entity_id}."
        )
    return resolved


# ---------------------------------------------------------------------------
# Application d'une convention sur une entité
# ---------------------------------------------------------------------------


async def _existing_link_for(
    entity_type: str, entity_id: int, db: AsyncSession
) -> Optional[DriveEntityLink]:
    stmt = select(DriveEntityLink).where(
        DriveEntityLink.entity_type == entity_type,
        DriveEntityLink.entity_id == entity_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def apply_convention_to_entity(
    convention_id: int,
    entity_type: str,
    entity_id: int,
    user_id: int,
    db: AsyncSession,
) -> DriveEntityLink:
    """Applique manuellement une convention à une entité.

    Étapes :

    1. Charge la convention (active uniquement).
    2. Charge l'entité Kratos cible.
    3. Vérifie qu'aucun :class:`DriveEntityLink` n'existe déjà pour
       ce couple ``(entity_type, entity_id)`` — sinon
       :class:`EntityAlreadyLinked`.
    4. Résout ``folder_name_template`` via :func:`resolve_folder_name`.
    5. Si ``template_folder_to_copy_drive_id`` défini → clone récursif
       du template ; sinon création d'un dossier vide.
    6. Crée chaque sous-dossier listé dans ``subfolders_to_create``.
    7. Persiste le :class:`DriveEntityLink` (avec ``convention_id``
       pour la traçabilité).

    Retourne le ``DriveEntityLink`` créé (non encore commité — l'appelant
    se charge du commit côté endpoint).
    """
    convention = await db.get(DriveConvention, convention_id)
    if convention is None:
        raise ConventionNotFound(
            f"Convention #{convention_id} introuvable."
        )
    if not convention.active:
        raise ConventionNotFound(
            f"Convention #{convention_id} est inactive — réactive-la "
            f"d'abord avant de l'appliquer."
        )
    if convention.entity_type != entity_type:
        raise ConventionMisconfigured(
            f"Type d'entité {entity_type!r} incompatible avec la "
            f"convention #{convention_id} (déclarée pour "
            f"{convention.entity_type!r})."
        )
    if not convention.parent_folder_drive_id:
        raise ConventionMisconfigured(
            f"Convention #{convention_id} n'a pas de dossier parent Drive "
            f"configuré (champ parent_folder_drive_id)."
        )
    if not convention.folder_name_template:
        raise ConventionMisconfigured(
            f"Convention #{convention_id} n'a pas de template de nom "
            f"(champ folder_name_template)."
        )

    # Charge l'entité — soulève EntityNotFound / UnsupportedEntityType
    # si besoin.
    await _load_entity(entity_type, entity_id, db)

    # Refuse de re-créer un lien existant (cf. docstring de
    # EntityAlreadyLinked).
    existing = await _existing_link_for(entity_type, entity_id, db)
    if existing is not None:
        raise EntityAlreadyLinked(
            f"Un lien Drive existe déjà pour {entity_type}#{entity_id} "
            f"(dossier {existing.drive_folder_name or existing.drive_folder_id!r}). "
            f"Supprime-le d'abord si tu veux appliquer une nouvelle convention."
        )

    # Résout le nom du dossier.
    folder_name = await resolve_folder_name(
        convention.folder_name_template, entity_type, entity_id, db
    )

    # Crée le dossier (copie template OU création vide).
    if convention.template_folder_to_copy_drive_id:
        new_folder = await drive_api.copy_folder_recursive(
            user_id,
            db,
            source_folder_id=convention.template_folder_to_copy_drive_id,
            parent_folder_id=convention.parent_folder_drive_id,
            new_name=folder_name,
        )
    else:
        new_folder = await drive_api.create_folder(
            user_id,
            db,
            parent_folder_id=convention.parent_folder_drive_id,
            folder_name=folder_name,
        )

    new_folder_id = new_folder.get("id")
    new_folder_name = new_folder.get("name") or folder_name

    # Sous-dossiers — un par un, en ignorant les chaines vides et les
    # doublons exacts (Phil peut taper la même valeur deux fois).
    subfolders = convention.subfolders_to_create or []
    if isinstance(subfolders, list):
        seen: set[str] = set()
        for raw in subfolders:
            if not raw:
                continue
            name = str(raw).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            try:
                await drive_api.create_folder(
                    user_id, db, new_folder_id, name
                )
            except Exception as exc:  # noqa: BLE001
                # Best-effort : on continue si un sous-dossier échoue,
                # plutôt que de laisser le dossier principal créé mais
                # un EntityLink jamais persisté. Phil verra l'audit log.
                log.warning(
                    "drive_conventions: creation sous-dossier %r echouee "
                    "dans %s : %s",
                    name,
                    new_folder_id,
                    exc,
                )

    # Persiste le lien entité ↔ dossier.
    link = DriveEntityLink(
        entity_type=entity_type,
        entity_id=entity_id,
        drive_folder_id=new_folder_id,
        drive_folder_name=new_folder_name,
        convention_id=convention.id,
        created_by_user_id=user_id,
    )
    db.add(link)
    await db.flush()
    return link


__all__ = [
    "ConventionEngineError",
    "ConventionNotFound",
    "EntityNotFound",
    "EntityAlreadyLinked",
    "UnsupportedEntityType",
    "ConventionMisconfigured",
    "apply_convention_to_entity",
    "resolve_folder_name",
    "get_supported_entity_types",
]
