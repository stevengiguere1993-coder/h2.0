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
  supportés et de leurs variables disponibles (legacy, basé sur le
  registry hardcodé), utilisé par l'UI pour populer les dropdowns du
  wizard de création de convention.

- :func:`get_entity_catalog` — catalogue COMPLET et introspecté des
  types d'entités "linkables" + leurs champs disponibles (colonnes
  SQLAlchemy utiles + relations déclarées). Sert à la nouvelle modale
  dynamique : Phil choisit un type, voit tous les champs sous forme de
  chips cliquables qui insèrent un placeholder ``{champ}`` dans le
  pattern de nommage. La résolution runtime de ces placeholders passe
  par l'extracteur générique :func:`_extract_generic` (via le
  ``variable_mapping`` de la convention).

Compatibilité : une convention SANS ``variable_mapping`` continue
d'utiliser l'extracteur hardcodé du registry (les 5 types historiques
fonctionnent à l'identique). Une convention AVEC ``variable_mapping``
non vide utilise l'extracteur générique par introspection — ce qui
permet de gérer N'IMPORTE quel type/champ sans hardcoder.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import inspect as sa_inspect
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
# Helpers de formatage
# ---------------------------------------------------------------------------


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


def _fmt_value(value: Any) -> str:
    """Formatte une valeur arbitraire en chaîne propre pour un nom de
    dossier. Dates -> ``YYYY-MM-DD`` ; None -> "" ; Decimal/float/int ->
    texte sans surprise ; bool -> "oui"/"non". Jamais d'exception."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return _fmt_date(value)
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, Decimal):
        # Evite les "10.00" inutiles : entier si pas de fraction.
        try:
            if value == value.to_integral_value():
                return str(int(value))
        except Exception:  # noqa: BLE001
            pass
        return str(value)
    return str(value)


# ---------------------------------------------------------------------------
# Registry hardcodé des types d'entités (LEGACY — rétrocompat)
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
# Les conventions SANS ``variable_mapping`` passent par ces extracteurs
# (comportement historique préservé). Les nouvelles conventions
# (créées via la modale dynamique) déclarent un ``variable_mapping`` et
# court-circuitent ce registry au profit de :func:`_extract_generic`.


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
            # LeadAnalysis a directement city/postal_code (champs extraits par parser/Gemini).
            # Champs directs sur la fiche d analyse (LeadAnalysis).
            city = getattr(la, "city", "") or ""
            postal_code = getattr(la, "postal_code", "") or ""

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
    """Métadonnées (LEGACY) pour les dropdowns du wizard frontend.

    Conservé pour rétrocompat (endpoint ``supported-entity-types``).
    La nouvelle modale dynamique utilise plutôt :func:`get_entity_catalog`.

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
# Catalogue d'entités introspecté (NOUVEAU)
# ---------------------------------------------------------------------------
#
# Liste DECLARATIVE et facile à étendre : pour ajouter un type d'entité
# "linkable" au catalogue, il suffit d'ajouter une ligne ici (key, label
# FR, model_path, et optionnellement quelques chemins de relation à
# exposer). L'introspection des colonnes fait le reste automatiquement.
#
# Champs :
# - ``key`` : identifiant stable (utilisé comme ``entity_type`` côté
#   convention). Pour les 5 types historiques, on réutilise EXACTEMENT
#   les clés du registry pour la cohérence.
# - ``label`` : libellé FR affiché dans le dropdown.
# - ``model_path`` : (module, classe) SQLAlchemy.
# - ``relation_paths`` : liste optionnelle de tuples
#   ``(path, label, type)`` pour exposer des champs accessibles via une
#   relation (ex. ``lead_analysis.city``). Le ``type`` est purement
#   indicatif pour l'UI.

_ENTITY_CATALOG: list[dict[str, Any]] = [
    {
        "key": "ProspectionDeal",
        "label": "Deal Pipeline (Prospection)",
        "model_path": ("app.models.prospection_deal", "ProspectionDeal"),
        "relation_paths": [
            ("lead_analysis.city", "Ville (lead lié)", "string"),
            ("lead_analysis.postal_code", "Code postal (lead lié)", "string"),
        ],
    },
    {
        "key": "DevlogProject",
        "label": "Projet Dev Logiciel",
        "model_path": ("app.models.devlog_project", "DevlogProject"),
        "relation_paths": [],
    },
    {
        "key": "DevlogClient",
        "label": "Client Dev Logiciel",
        "model_path": ("app.models.devlog_client", "DevlogClient"),
        "relation_paths": [],
    },
    {
        "key": "ProspectionLead",
        "label": "Lead Prospection",
        "model_path": ("app.models.prospection_lead", "ProspectionLead"),
        "relation_paths": [],
    },
    {
        "key": "ConstructionProject",
        "label": "Projet Construction",
        "model_path": ("app.models.project", "Project"),
        "relation_paths": [],
    },
    {
        "key": "Entreprise",
        "label": "Entreprise",
        "model_path": ("app.models.entreprise", "Entreprise"),
        "relation_paths": [],
    },
    {
        "key": "Immeuble",
        "label": "Immeuble (Immobilier)",
        "model_path": ("app.models.immobilier", "Immeuble"),
        "relation_paths": [],
    },
]


# Types Python considérés "utiles" (affichables dans un nom de dossier).
# On exclut le binaire/JSON.
_USEFUL_PY_TYPES = (str, int, float, Decimal, bool, date, datetime)

# Noms de colonnes techniques à exclure du catalogue (clés internes,
# tokens, secrets, blobs). On garde les colonnes "métier".
_EXCLUDED_EXACT = {
    "id",
    "password",
    "password_hash",
    "hashed_password",
}
_EXCLUDED_SUFFIXES = (
    "_id",
    "_token",
    "_blob",
    "_image",
    "_hash",
    "_ip",
    "_content_type",
    "_secret",
)
_EXCLUDED_CONTAINS = (
    "token",
    "secret",
    "password",
)

# Traductions FR pour les noms de colonnes courants (sinon dérivation
# automatique depuis le nom snake_case).
_FIELD_LABELS_FR: dict[str, str] = {
    "name": "Nom",
    "address": "Adresse",
    "city": "Ville",
    "postal_code": "Code postal",
    "neq": "NEQ",
    "type": "Type",
    "description": "Description",
    "notes": "Notes",
    "matricule": "Matricule",
    "created_at": "Date de création",
    "updated_at": "Date de mise à jour",
    "purchase_date": "Date d'achat",
    "purchase_price": "Prix d'achat",
    "annee_construction": "Année de construction",
    "nb_logements": "Nombre de logements",
    "priority": "Priorité",
    "status": "Statut",
    "email": "Courriel",
    "phone": "Téléphone",
}


def _humanize_field(col_name: str) -> str:
    """Déduit un label FR lisible depuis un nom de colonne snake_case."""
    if col_name in _FIELD_LABELS_FR:
        return _FIELD_LABELS_FR[col_name]
    words = col_name.replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else col_name


def _py_type_label(python_type: Any) -> str:
    """Type lisible pour l'UI (string/number/date/boolean)."""
    try:
        if python_type in (datetime, date):
            return "date"
        if python_type is bool:
            return "boolean"
        if python_type in (int, float, Decimal):
            return "number"
    except Exception:  # noqa: BLE001
        pass
    return "string"


def _is_useful_column(col_name: str, python_type: Any) -> bool:
    """Filtre les colonnes "métier" affichables. created_at/updated_at
    sont gérés explicitement ailleurs (toujours inclus)."""
    if col_name in _EXCLUDED_EXACT:
        return False
    if any(col_name.endswith(suf) for suf in _EXCLUDED_SUFFIXES):
        return False
    if any(frag in col_name for frag in _EXCLUDED_CONTAINS):
        return False
    if python_type is None:
        return False
    try:
        if not issubclass(python_type, _USEFUL_PY_TYPES):
            return False
    except TypeError:
        return False
    return True


def _resolve_model(model_path: tuple[str, str]) -> Any:
    import importlib

    module_path, class_name = model_path
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def get_entity_catalog() -> list[dict[str, Any]]:
    """Catalogue COMPLET des types d'entités linkables + champs dispo.

    Pour chaque type déclaré dans :data:`_ENTITY_CATALOG` ::

        {
            "key": "Immeuble",
            "label": "Immeuble (Immobilier)",
            "fields": [
                {"path": "name", "label": "Nom", "type": "string"},
                {"path": "address", "label": "Adresse", "type": "string"},
                {"path": "created_at", "label": "Date de création", "type": "date"},
                ...
            ]
        }

    Les ``fields`` sont obtenus par INTROSPECTION des colonnes du modèle
    SQLAlchemy (en gardant str/text/date/datetime/numeric et en excluant
    les clés techniques / tokens / blobs), plus les ``relation_paths``
    déclarés, plus ``created_at``/``updated_at`` toujours présents.

    Robuste : si un modèle ne peut être importé/inspecté, il est ignoré
    (jamais d'exception qui casserait l'endpoint).
    """
    catalog: list[dict[str, Any]] = []
    for entry in _ENTITY_CATALOG:
        try:
            model = _resolve_model(entry["model_path"])
            mapper = sa_inspect(model)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "drive entity-catalog: introspection impossible pour %s : %s",
                entry.get("key"),
                exc,
            )
            continue

        fields: list[dict[str, str]] = []
        seen_paths: set[str] = set()

        for column in mapper.columns:
            col_name = column.key
            try:
                python_type = column.type.python_type
            except Exception:  # noqa: BLE001
                python_type = None
            # created_at/updated_at gérés en fin de liste (libellés fixes).
            if col_name in ("created_at", "updated_at"):
                continue
            if not _is_useful_column(col_name, python_type):
                continue
            if col_name in seen_paths:
                continue
            seen_paths.add(col_name)
            fields.append(
                {
                    "path": col_name,
                    "label": _humanize_field(col_name),
                    "type": _py_type_label(python_type),
                }
            )

        # Relations déclarées explicitement.
        for path, label, ftype in entry.get("relation_paths", []):
            if path in seen_paths:
                continue
            seen_paths.add(path)
            fields.append({"path": path, "label": label, "type": ftype})

        # Toujours offrir les dates de création / mise à jour si le
        # modèle les possède.
        col_keys = {c.key for c in mapper.columns}
        for date_col, date_label in (
            ("created_at", "Date de création"),
            ("updated_at", "Date de mise à jour"),
        ):
            if date_col in col_keys and date_col not in seen_paths:
                seen_paths.add(date_col)
                fields.append(
                    {"path": date_col, "label": date_label, "type": "date"}
                )

        catalog.append(
            {
                "key": entry["key"],
                "label": entry["label"],
                "fields": fields,
            }
        )

    return catalog


# ---------------------------------------------------------------------------
# Extracteur générique par introspection
# ---------------------------------------------------------------------------


def _resolve_field_path(entity: Any, field_path: str) -> Any:
    """Résout ``field_path`` par getattr en chaîne sur ``entity``.

    Supporte les relations simples (ex. ``lead_analysis.city``). Retourne
    ``None`` dès qu'un maillon est introuvable ou None. Ne lève jamais.
    """
    current: Any = entity
    for part in field_path.split("."):
        if current is None:
            return None
        try:
            current = getattr(current, part)
        except Exception:  # noqa: BLE001
            return None
    return current


def _extract_generic(
    entity: Any, db: AsyncSession, mapping: dict[str, str]
) -> dict[str, str]:
    """Extracteur générique : résout chaque ``var_key -> field_path``.

    Pour chaque entrée du ``variable_mapping`` :
    - résout le chemin via :func:`_resolve_field_path` (getattr en chaîne,
      supporte les relations),
    - formate (dates -> ``YYYY-MM-DD``, etc.) via :func:`_fmt_value`,
    - met ``""`` si introuvable.

    Aucune exception ne remonte : un champ qui plante donne ``""``.
    ``db`` est accepté pour symétrie avec les extracteurs hardcodés (et
    pour évolutions futures), même s'il n'est pas utilisé ici — les
    relations sont chargées paresseusement par l'ORM si nécessaire.
    """
    out: dict[str, str] = {}
    for var_key, field_path in (mapping or {}).items():
        if not field_path:
            out[var_key] = ""
            continue
        try:
            raw = _resolve_field_path(entity, field_path)
            out[var_key] = _fmt_value(raw)
        except Exception:  # noqa: BLE001
            out[var_key] = ""
    return out


# ---------------------------------------------------------------------------
# Chargement d'une entité Kratos par (type, id)
# ---------------------------------------------------------------------------


# Index secondaire des types du catalogue (pour charger une entité même
# si elle n'est PAS dans le registry hardcodé — ex. Entreprise/Immeuble).
_CATALOG_BY_KEY: dict[str, dict[str, Any]] = {e["key"]: e for e in _ENTITY_CATALOG}


def _model_path_for(entity_type: str) -> Optional[tuple[str, str]]:
    """Retourne le ``model_path`` du type, depuis le registry OU le
    catalogue. ``None`` si type inconnu des deux."""
    if entity_type in _ENTITY_REGISTRY:
        return _ENTITY_REGISTRY[entity_type]["model_path"]
    entry = _CATALOG_BY_KEY.get(entity_type)
    if entry is not None:
        return entry["model_path"]
    return None


async def _load_entity(
    entity_type: str, entity_id: int, db: AsyncSession
) -> Any:
    model_path = _model_path_for(entity_type)
    if model_path is None:
        supported = sorted(set(_ENTITY_REGISTRY) | set(_CATALOG_BY_KEY))
        raise UnsupportedEntityType(
            f"Type d'entité non supporté par les conventions : {entity_type}. "
            f"Types supportés : {', '.join(supported)}."
        )
    cls = _resolve_model(model_path)
    entity = await db.get(cls, entity_id)
    if entity is None:
        raise EntityNotFound(
            f"{entity_type} #{entity_id} introuvable en base."
        )
    return entity


# ---------------------------------------------------------------------------
# Résolution du template de nom
# ---------------------------------------------------------------------------


_TEMPLATE_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


async def _variables_for(
    convention: Optional[DriveConvention],
    entity_type: str,
    entity: Any,
    db: AsyncSession,
) -> dict[str, str]:
    """Calcule le dict de variables pour interpoler le template.

    - Si la convention a un ``variable_mapping`` non vide -> extracteur
      GENERIQUE par introspection (gère N'IMPORTE quel type/champ).
    - Sinon -> extracteur HARDCODE du registry (rétrocompat totale pour
      les 5 types et conventions existantes).
    """
    mapping = getattr(convention, "variable_mapping", None) if convention else None
    if mapping:
        return _extract_generic(entity, db, mapping)

    entry = _ENTITY_REGISTRY.get(entity_type)
    if entry is None:
        # Pas de mapping ET pas d'extracteur hardcodé -> on ne sait pas
        # résoudre. Plutôt que crasher, on renvoie un dict vide (les
        # placeholders resteront tels quels avec un warning).
        return {}
    return await entry["extract"](entity, db)


async def resolve_folder_name(
    template: str,
    entity_type: str,
    entity_id: int,
    db: AsyncSession,
    convention: Optional[DriveConvention] = None,
) -> str:
    """Résout ``template`` avec les variables disponibles pour ce type.

    Si ``convention`` est fournie et porte un ``variable_mapping`` non
    vide, on utilise l'extracteur générique (introspection). Sinon on
    retombe sur l'extracteur hardcodé du registry (rétrocompat).

    Variables manquantes (clé absente ou valeur vide) : on laisse le
    placeholder ``{var}`` tel quel + on logge un warning. Ne crash pas —
    l'UI affichera un nom partiellement résolu, à Phil de corriger sa
    convention.

    Espaces superflus dûs à des variables vides : nettoyés à la marge
    (séquences ``,  ,``, ``  ``) pour des noms propres.
    """
    if not template:
        raise ConventionMisconfigured(
            "Le template de nom de la convention est vide."
        )

    # Si pas de mapping et type inconnu du registry/catalogue -> erreur
    # claire (comportement legacy conservé pour les types historiques).
    has_mapping = bool(getattr(convention, "variable_mapping", None)) if convention else False
    if (
        not has_mapping
        and entity_type not in _ENTITY_REGISTRY
        and entity_type not in _CATALOG_BY_KEY
    ):
        raise UnsupportedEntityType(
            f"Type d'entité non supporté par les conventions : {entity_type}."
        )

    entity = await _load_entity(entity_type, entity_id, db)
    variables = await _variables_for(convention, entity_type, entity, db)

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
        # Variable absente ou vide -> on laisse le placeholder tel quel.
        return match.group(0)

    resolved = _TEMPLATE_VAR_RE.sub(_replace, template)

    # Nettoyage léger : si une variable vide a laissé "X, , Y" -> "X, Y".
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
    4. Résout ``folder_name_template`` via :func:`resolve_folder_name`
       (extracteur générique si la convention a un ``variable_mapping``,
       sinon registry hardcodé).
    5. Si ``template_folder_to_copy_drive_id`` défini -> clone récursif
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

    # Résout le nom du dossier (en passant la convention pour activer
    # l'extracteur générique si un variable_mapping est présent).
    folder_name = await resolve_folder_name(
        convention.folder_name_template,
        entity_type,
        entity_id,
        db,
        convention=convention,
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
    "get_entity_catalog",
]
