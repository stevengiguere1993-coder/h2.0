"""Pydantic schemas pour le volet Gestion d'entreprises."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Entreprise ─────────────────────────────────────────────────────────


class EntrepriseBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    neq: Optional[str] = Field(default=None, max_length=32)
    type: str = Field(default="gestion", max_length=32)
    color_accent: str = Field(default="#7c3aed", pattern=r"^#[0-9a-fA-F]{6}$")
    description: Optional[str] = None
    drive_folder_url: Optional[str] = Field(default=None, max_length=1024)
    is_active: bool = True


class EntrepriseCreate(EntrepriseBase):
    pass


class EntrepriseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    neq: Optional[str] = Field(default=None, max_length=32)
    type: Optional[str] = Field(default=None, max_length=32)
    color_accent: Optional[str] = Field(
        default=None, pattern=r"^#[0-9a-fA-F]{6}$"
    )
    description: Optional[str] = None
    drive_folder_url: Optional[str] = Field(default=None, max_length=1024)
    is_active: Optional[bool] = None


class EntrepriseRead(EntrepriseBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    monday_board_id: Optional[str] = None
    monday_board_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ─── Tâche ─────────────────────────────────────────────────────────────


class EntrepriseTacheBase(BaseModel):
    entreprise_id: int
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    departement: Optional[str] = Field(default=None, max_length=32)
    # Défaut « a_faire » — colonne « À faire » (sky). Plus pertinent
    # qu'un démarrage en À venir : l'utilisateur qui crée une tâche
    # veut généralement qu'elle soit déjà engagée.
    status: str = Field(default="a_faire", max_length=16)
    # Priorité Monday-style (alignée sur les tâches du Pipeline).
    # Défaut « non_assigne » — pastille grise — tant que l'utilisateur
    # n'a pas choisi une priorité explicite.
    priority: str = Field(
        default="non_assigne",
        pattern=r"^(non_assigne|urgent|eleve|moyenne|faible)$"
    )
    impact: Optional[int] = Field(default=None, ge=1, le=10)
    confidence: Optional[int] = Field(default=None, ge=1, le=10)
    effort: Optional[int] = Field(default=None, ge=1, le=10)
    # Source de vérité — liste d'utilisateurs assignés. Le scalaire
    # legacy `assignee_user_id` reste accepté + maintenu (= primary,
    # premier de la liste) pour les anciens consumers.
    assignee_user_ids: Optional[List[int]] = None
    assignee_user_id: Optional[int] = None
    due_date: Optional[date] = None
    recurrence: Optional[str] = Field(default=None, max_length=16)
    tags_json: Optional[str] = None
    # Immeubles concernés par la tâche (multi-select dans la fiche).
    immeuble_ids: Optional[List[int]] = None


class EntrepriseTacheCreate(EntrepriseTacheBase):
    pass


class EntrepriseTacheUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    departement: Optional[str] = Field(default=None, max_length=32)
    status: Optional[str] = Field(default=None, max_length=16)
    priority: Optional[str] = Field(
        default=None, pattern=r"^(non_assigne|urgent|eleve|moyenne|faible)$"
    )
    impact: Optional[int] = Field(default=None, ge=1, le=10)
    confidence: Optional[int] = Field(default=None, ge=1, le=10)
    effort: Optional[int] = Field(default=None, ge=1, le=10)
    assignee_user_ids: Optional[List[int]] = None
    assignee_user_id: Optional[int] = None
    due_date: Optional[date] = None
    recurrence: Optional[str] = Field(default=None, max_length=16)
    tags_json: Optional[str] = None
    completed_at: Optional[datetime] = None
    # Permet de déplacer une tâche d'une entreprise vers une autre
    # via le bouton « Déplacer » dans la carte.
    entreprise_id: Optional[int] = Field(default=None, gt=0)
    immeuble_ids: Optional[List[int]] = None
    # Ordre manuel (drag & drop dans le tableau).
    position: Optional[int] = None


class EntrepriseTacheRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    entreprise_id: int
    title: str
    description: Optional[str] = None
    departement: Optional[str] = None
    status: str = "todo"
    priority: str = "non_assigne"
    impact: Optional[int] = None
    confidence: Optional[int] = None
    effort: Optional[int] = None
    # Champ legacy = primary (premier de la liste). Conservé pour
    # les vieux clients qui n'auraient pas migré.
    assignee_user_id: Optional[int] = None
    # Source de vérité — liste d'utilisateurs assignés.
    assignee_user_ids: List[int] = Field(default_factory=list)
    # Immeubles liés à la tâche.
    immeuble_ids: List[int] = Field(default_factory=list)
    # Position manuelle (drag & drop). 0 = pas réordonné — le frontend
    # retombe sur un classement par score.
    position: int = 0
    due_date: Optional[date] = None
    completed_at: Optional[datetime] = None
    recurrence: Optional[str] = None
    tags_json: Optional[str] = None
    monday_item_id: Optional[str] = None
    monday_board_id: Optional[str] = None
    monday_group_title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Score calculé serveur-side (ICE × multiplicateur d'urgence). Optionnel
    # — None si l'un des champs ICE est absent.
    score: Optional[float] = None


class TacheImportResult(BaseModel):
    """Résultat du POST /entreprises/import-monday-tasks."""

    boards_processed: int
    entreprises_created: int
    entreprises_updated: int
    taches_created: int
    taches_updated: int
    errors: List[str] = Field(default_factory=list)
