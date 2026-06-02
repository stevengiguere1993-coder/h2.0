"""Schémas Pydantic pour les Drive Page Modules — Phase 7.

Un "page module" pilote l'affichage de la section Drive
(``<EntityDriveSection>``) sur les pages d'un type d'entité Kratos.

Couvre :

- Lecture complète d'un module (admin) avec stats de liens.
- Statut minimal ``{active, display_title}`` consommé par le composant.
- Upsert (PATCH) du toggle + titre.
- Création explicite (POST).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DrivePageModuleRead(BaseModel):
    """Représentation complète d'un module pour le tableau Settings."""

    id: int
    entity_type: str
    active: bool
    display_title: Optional[str] = None
    display_order: int
    # Métadonnées du registry (navigation par pôle dans Settings).
    pole: Optional[str] = None
    label: Optional[str] = None
    route: Optional[str] = None
    # Nombre de DriveEntityLink existants pour ce type (stat affichage).
    linked_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DrivePageModuleStatus(BaseModel):
    """Statut minimal consommé par ``<EntityDriveSection>``.

    Quand le module n'existe pas en BDD, l'endpoint renvoie
    ``{active: False, display_title: None}`` — jamais un 404.
    """

    active: bool = False
    display_title: Optional[str] = None
    # Indique si une convention Drive existe pour ce type (utilisé par
    # le composant pour afficher ou non le bouton "Créer auto").
    has_convention: bool = False


class DrivePageModulePatch(BaseModel):
    """Body PATCH — upsert du toggle et/ou du titre.

    Tous les champs sont optionnels : seuls ceux présents sont
    appliqués. Si la ligne n'existe pas encore, elle est créée.
    """

    active: Optional[bool] = None
    display_title: Optional[str] = Field(default=None, max_length=128)
    display_order: Optional[int] = Field(default=None, ge=0)


class DrivePageModuleCreate(BaseModel):
    """Body POST — création explicite d'un module."""

    entity_type: str = Field(min_length=1, max_length=64)
    active: bool = False
    display_title: Optional[str] = Field(default=None, max_length=128)
    display_order: int = Field(default=0, ge=0)
