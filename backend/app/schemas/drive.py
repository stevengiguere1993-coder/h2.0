"""Schémas Pydantic pour les endpoints Drive (Phase 2).

Une représentation normalisée renvoyée par l'API Kratos — l'UI ne voit
jamais la forme brute de l'API Drive de Google, ce qui nous permet de
changer de format sans casser le frontend.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

from app.services.drive_api import FOLDER_MIME


class DriveOwner(BaseModel):
    """Propriétaire d'un fichier Drive."""

    display_name: Optional[str] = Field(default=None, alias="displayName")
    email_address: Optional[str] = Field(default=None, alias="emailAddress")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class DriveFile(BaseModel):
    """Représentation normalisée d'un fichier ou dossier Drive."""

    id: str
    name: str
    mime_type: str = Field(alias="mimeType")
    size: Optional[str] = None  # Google retourne la taille en string (octets).
    modified_time: Optional[datetime] = Field(default=None, alias="modifiedTime")
    created_time: Optional[datetime] = Field(default=None, alias="createdTime")
    owners: List[DriveOwner] = Field(default_factory=list)
    parents: List[str] = Field(default_factory=list)
    thumbnail_link: Optional[str] = Field(default=None, alias="thumbnailLink")
    web_view_link: Optional[str] = Field(default=None, alias="webViewLink")
    icon_link: Optional[str] = Field(default=None, alias="iconLink")
    trashed: Optional[bool] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    @computed_field  # type: ignore[misc]
    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME


class DriveFolderContents(BaseModel):
    """Liste paginée du contenu d'un dossier."""

    files: List[DriveFile]
    next_page_token: Optional[str] = None


class DriveFolderPathSegment(BaseModel):
    id: str
    name: str


class DriveFolderPath(BaseModel):
    """Breadcrumbs : segments racine → dossier courant."""

    segments: List[DriveFolderPathSegment]


class DrivePermission(BaseModel):
    """Permission de partage sur un fichier."""

    id: str
    email_address: Optional[str] = Field(default=None, alias="emailAddress")
    role: str
    display_name: Optional[str] = Field(default=None, alias="displayName")
    type: Optional[str] = None  # user, group, domain, anyone

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class DrivePermissionList(BaseModel):
    permissions: List[DrivePermission]


class DrivePreviewUrl(BaseModel):
    """URL prête à embed dans un iframe côté frontend."""

    preview_url: str
    web_view_link: Optional[str] = None


# ---------------------------------------------------------------------------
# Requêtes (bodies)
# ---------------------------------------------------------------------------


class DriveFilePatch(BaseModel):
    """Body PATCH /api/v1/drive/files/{file_id} — rename et/ou move."""

    name: Optional[str] = None
    parent_folder_id: Optional[str] = None
    old_parent_folder_id: Optional[str] = None


class DriveCreateFolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class DriveCopyFolderRequest(BaseModel):
    parent_folder_id: str
    new_name: Optional[str] = Field(default=None, max_length=255)


class DriveShareRequest(BaseModel):
    email: EmailStr
    role: str = Field(default="reader", pattern="^(reader|commenter|writer)$")
    send_notification: bool = True
    message: str = ""


class DriveSearchResult(BaseModel):
    files: List[DriveFile]
    next_page_token: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers de conversion (raw dict Google → DriveFile)
# ---------------------------------------------------------------------------


def normalize_drive_file(raw: dict[str, Any]) -> DriveFile:
    """Construit un DriveFile à partir du dict raw renvoyé par l'API Google."""
    return DriveFile.model_validate(raw)
