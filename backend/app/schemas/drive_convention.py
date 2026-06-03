"""Schémas Pydantic pour les Drive Conventions et Entity Links — Phase 4.

Couvre :

- CRUD des :class:`DriveConvention` (admin/owner only via le router).
- Action ``apply`` (corps minimal ``{entity_type, entity_id}``).
- Liste des types d'entités supportées + variables disponibles.
- CRUD minimal des :class:`DriveEntityLink` (création manuelle d'un
  lien sans passer par une convention, lecture, suppression).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# DriveConvention — schémas de lecture
# ---------------------------------------------------------------------------


class DriveConventionRead(BaseModel):
    """Représentation complète d'une convention pour le frontend."""

    id: int
    name: str
    entity_type: str
    trigger_event: str
    parent_folder_drive_id: Optional[str] = None
    folder_name_template: Optional[str] = None
    template_folder_to_copy_drive_id: Optional[str] = None
    subfolders_to_create: Optional[List[str]] = None
    auto_link_to_entity: bool = True
    status_to_parent_map: Optional[dict[str, Any]] = None
    active: bool
    priority: int = 100
    description: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# DriveConvention — création / patch
# ---------------------------------------------------------------------------


_VALID_TRIGGER_EVENTS = {"created", "status_changed", "manuel"}


class DriveConventionCreate(BaseModel):
    """Body POST /api/v1/drive/conventions.

    Tous les champs métier sont éditables sauf l'horodatage et l'auteur
    (posés serveur-side). Les champs non requis tolèrent ``None`` pour
    correspondre à la "création vide" du wizard quand Phil sauvegarde
    un brouillon sans avoir encore configuré son parent Drive.
    """

    name: str = Field(min_length=1, max_length=255)
    entity_type: str = Field(min_length=1, max_length=64)
    trigger_event: str = Field(default="manuel", max_length=32)
    parent_folder_drive_id: Optional[str] = Field(default=None, max_length=128)
    folder_name_template: Optional[str] = Field(default=None, max_length=255)
    template_folder_to_copy_drive_id: Optional[str] = Field(
        default=None, max_length=128
    )
    subfolders_to_create: Optional[List[str]] = None
    auto_link_to_entity: bool = True
    status_to_parent_map: Optional[dict[str, Any]] = None
    active: bool = False  # Toujours inactif par défaut (Phil active ensuite).
    priority: int = 100
    description: Optional[str] = None

    def validated(self) -> "DriveConventionCreate":
        """Hook de validation cross-field appelé par l'endpoint.

        Pydantic v2 ne fait pas de validator class auto-déclaré pour
        ``trigger_event`` parce qu'on veut un message explicite côté
        UI plutôt qu'une erreur générique de pattern. On délègue donc
        la vérification ici.
        """
        if self.trigger_event not in _VALID_TRIGGER_EVENTS:
            raise ValueError(
                f"trigger_event invalide : {self.trigger_event!r}. "
                f"Valeurs acceptées : {', '.join(sorted(_VALID_TRIGGER_EVENTS))}."
            )
        return self


class DriveConventionPatch(BaseModel):
    """Body PATCH /api/v1/drive/conventions/{id}. Tous champs optionnels."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    entity_type: Optional[str] = Field(default=None, min_length=1, max_length=64)
    trigger_event: Optional[str] = Field(default=None, max_length=32)
    parent_folder_drive_id: Optional[str] = Field(default=None, max_length=128)
    folder_name_template: Optional[str] = Field(default=None, max_length=255)
    template_folder_to_copy_drive_id: Optional[str] = Field(
        default=None, max_length=128
    )
    subfolders_to_create: Optional[List[str]] = None
    auto_link_to_entity: Optional[bool] = None
    status_to_parent_map: Optional[dict[str, Any]] = None
    active: Optional[bool] = None
    priority: Optional[int] = None
    description: Optional[str] = None

    def validated(self) -> "DriveConventionPatch":
        if (
            self.trigger_event is not None
            and self.trigger_event not in _VALID_TRIGGER_EVENTS
        ):
            raise ValueError(
                f"trigger_event invalide : {self.trigger_event!r}. "
                f"Valeurs acceptées : {', '.join(sorted(_VALID_TRIGGER_EVENTS))}."
            )
        return self


# ---------------------------------------------------------------------------
# Action ``apply``
# ---------------------------------------------------------------------------


class DriveConventionApplyRequest(BaseModel):
    """Body POST /api/v1/drive/conventions/{id}/apply."""

    entity_type: str = Field(min_length=1, max_length=64)
    entity_id: int = Field(ge=1)


class DriveConventionApplyResult(BaseModel):
    """Résultat enrichi d'un apply réussi pour l'UI.

    Reprend le lien créé + un champ ``subfolders_created`` qui aide
    Phil à valider visuellement ce qu'il a généré (l'UI affiche
    "Sous-dossiers créés : Photos, Documents, ...").
    """

    link: "DriveEntityLinkRead"
    subfolders_created: List[str] = Field(default_factory=list)
    drive_folder_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Métadonnées entités supportées
# ---------------------------------------------------------------------------


class SupportedEntityVariable(BaseModel):
    key: str
    label: str
    description: Optional[str] = None


class SupportedEntityType(BaseModel):
    key: str
    label: str
    variables: List[SupportedEntityVariable]


# ---------------------------------------------------------------------------
# DriveEntityLink — schémas
# ---------------------------------------------------------------------------


class DriveEntityLinkRead(BaseModel):
    """Lien entité Kratos ↔ dossier Drive (un par couple
    ``entity_type, entity_id``).
    """

    id: int
    entity_type: str
    entity_id: int
    drive_folder_id: str
    drive_folder_name: Optional[str] = None
    drive_folder_path: Optional[str] = None
    convention_id: Optional[int] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DriveEntityLinkCreate(BaseModel):
    """Body POST /api/v1/drive/entity-links — lien manuel sans
    convention. Sert à rattacher un dossier Drive existant à une entité
    Kratos sans passer par le moteur d'exécution."""

    entity_type: str = Field(min_length=1, max_length=64)
    # ge=0 : entity_id=0 est la convention des liens "Drive de page"
    # (singleton) — un dossier unique pour une page générale (organigramme,
    # vision…). Les fiches utilisent un id réel (>=1).
    entity_id: int = Field(ge=0)
    drive_folder_id: str = Field(min_length=1, max_length=128)
    drive_folder_name: Optional[str] = Field(default=None, max_length=255)


class DriveEntityLinkPatch(BaseModel):
    """Body PATCH /api/v1/drive/entity-links/{id} — re-cible un lien
    existant vers un autre dossier Drive (cas « mauvais dossier lié »).

    Seul ``drive_folder_id`` est requis ; ``drive_folder_name`` est mis à
    jour si fourni. On ne change jamais ``entity_type``/``entity_id`` (la
    cible Kratos reste la même)."""

    drive_folder_id: str = Field(min_length=1, max_length=128)
    drive_folder_name: Optional[str] = Field(default=None, max_length=255)


# Forward refs : DriveConventionApplyResult dépend de DriveEntityLinkRead.
DriveConventionApplyResult.model_rebuild()


__all__ = [
    "DriveConventionRead",
    "DriveConventionCreate",
    "DriveConventionPatch",
    "DriveConventionApplyRequest",
    "DriveConventionApplyResult",
    "DriveEntityLinkRead",
    "DriveEntityLinkCreate",
    "DriveEntityLinkPatch",
    "SupportedEntityType",
    "SupportedEntityVariable",
]

