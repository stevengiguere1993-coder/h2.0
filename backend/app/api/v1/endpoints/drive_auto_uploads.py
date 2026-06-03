"""Endpoints REST des règles d'auto-upload Drive — Phase 6.

CRUD des :class:`DriveAutoUpload` (règles « document généré → sous-dossier
Drive de l'entité »). Tous protégés par :data:`RequireAdminOrOwner`. Les
mutations posent un audit log dans la table générique ``audit_logs``
(opération de CONFIGURATION, distincte des ``drive_audit_logs`` qui
tracent les uploads réels).

Surface :

- ``GET    /api/v1/drive/auto-uploads`` — liste, filtres ``document_type``,
  ``entity_type``, ``active``.
- ``GET    /api/v1/drive/auto-uploads/{id}``
- ``POST   /api/v1/drive/auto-uploads`` — crée une règle (inactive par
  défaut).
- ``PATCH  /api/v1/drive/auto-uploads/{id}`` — toggle ``active`` / édite
  les templates / la stratégie.
- ``DELETE /api/v1/drive/auto-uploads/{id}`` — soft-delete (``active=False``).
- ``GET    /api/v1/drive/auto-uploads/meta`` — métadonnées (types de
  documents, types d'entités, stratégies) pour alimenter les dropdowns
  du frontend.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.api.deps import DBSession, RequireAdminOrOwner
from app.models.drive_auto_upload import DriveAutoUpload
from app.services.audit import log_action

log = logging.getLogger(__name__)

router = APIRouter(prefix="/drive/auto-uploads", tags=["drive-auto-uploads"])


# ---------------------------------------------------------------------------
# Métadonnées (dropdowns frontend)
# ---------------------------------------------------------------------------

# document_type reconnus (cf. dispatcher + endpoints instrumentés).
_DOCUMENT_TYPES: list[dict[str, str]] = [
    {"key": "fiche_analyse", "label": "Fiche d'analyse (PDF)"},
    {"key": "offre_pptx", "label": "Offre d'investissement (PPTX)"},
    {"key": "nda_signed", "label": "NDA signé (PDF)"},
    {"key": "soumission_pdf", "label": "Soumission Dev Log (PDF)"},
    {"key": "facture_pdf", "label": "Facture Dev Log (PDF)"},
]

# entity_type reconnus (doivent matcher les DriveEntityLink).
_ENTITY_TYPES: list[dict[str, str]] = [
    {"key": "ProspectionDeal", "label": "Deal Pipeline (Prospection)"},
    {"key": "DevlogClient", "label": "Client Dev Logiciel"},
    {"key": "DevlogProject", "label": "Projet Dev Logiciel"},
    {"key": "ConstructionProject", "label": "Projet Construction"},
]

_OVERWRITE_STRATEGIES: list[dict[str, str]] = [
    {
        "key": "overwrite",
        "label": "Remplacer",
        "description": (
            "Corbeille le fichier de même nom puis dépose le nouveau "
            "(un seul fichier à jour)."
        ),
    },
    {
        "key": "version",
        "label": "Versionner",
        "description": (
            "Ajoute un suffixe horodaté — conserve tout l'historique."
        ),
    },
    {
        "key": "keep_both",
        "label": "Garder les deux",
        "description": (
            "Dépose sans vérifier — Drive tolère les doublons de nom."
        ),
    },
]

_VALID_DOCUMENT_TYPES = {d["key"] for d in _DOCUMENT_TYPES}
_VALID_ENTITY_TYPES = {e["key"] for e in _ENTITY_TYPES}
_VALID_STRATEGIES = {s["key"] for s in _OVERWRITE_STRATEGIES}


# ---------------------------------------------------------------------------
# Schémas
# ---------------------------------------------------------------------------


class DriveAutoUploadRead(BaseModel):
    id: int
    name: str
    document_type: str
    entity_type: str
    subfolder_path_template: Optional[str] = None
    file_name_template: Optional[str] = None
    overwrite_strategy: str
    active: bool
    description: Optional[str] = None
    # Lecture seule : null = règle seedée par le système (exemple
    # pré-rempli), un id = règle créée par un utilisateur humain. Le
    # frontend s'en sert pour afficher un badge « Exemple ».
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DriveAutoUploadCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    document_type: str = Field(..., max_length=64)
    entity_type: str = Field(..., max_length=64)
    subfolder_path_template: Optional[str] = Field(default=None, max_length=512)
    file_name_template: Optional[str] = Field(default=None, max_length=255)
    overwrite_strategy: str = Field(default="version", max_length=32)
    active: bool = False
    description: Optional[str] = None

    @field_validator("document_type")
    @classmethod
    def _check_document_type(cls, v: str) -> str:
        if v not in _VALID_DOCUMENT_TYPES:
            raise ValueError(
                f"document_type invalide : {v}. Attendu : "
                f"{', '.join(sorted(_VALID_DOCUMENT_TYPES))}."
            )
        return v

    @field_validator("entity_type")
    @classmethod
    def _check_entity_type(cls, v: str) -> str:
        if v not in _VALID_ENTITY_TYPES:
            raise ValueError(
                f"entity_type invalide : {v}. Attendu : "
                f"{', '.join(sorted(_VALID_ENTITY_TYPES))}."
            )
        return v

    @field_validator("overwrite_strategy")
    @classmethod
    def _check_strategy(cls, v: str) -> str:
        if v not in _VALID_STRATEGIES:
            raise ValueError(
                f"overwrite_strategy invalide : {v}. Attendu : "
                f"{', '.join(sorted(_VALID_STRATEGIES))}."
            )
        return v


class DriveAutoUploadPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    subfolder_path_template: Optional[str] = Field(default=None, max_length=512)
    file_name_template: Optional[str] = Field(default=None, max_length=255)
    overwrite_strategy: Optional[str] = Field(default=None, max_length=32)
    active: Optional[bool] = None
    description: Optional[str] = None

    @field_validator("overwrite_strategy")
    @classmethod
    def _check_strategy(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_STRATEGIES:
            raise ValueError(
                f"overwrite_strategy invalide : {v}. Attendu : "
                f"{', '.join(sorted(_VALID_STRATEGIES))}."
            )
        return v


class AutoUploadMeta(BaseModel):
    document_types: list[dict[str, str]]
    entity_types: list[dict[str, str]]
    overwrite_strategies: list[dict[str, str]]


# ---------------------------------------------------------------------------
# Routes — métadonnées (avant la route à param pour éviter l'interception)
# ---------------------------------------------------------------------------


@router.get("/meta", response_model=AutoUploadMeta)
async def get_auto_upload_meta(user: RequireAdminOrOwner) -> AutoUploadMeta:
    """Métadonnées pour alimenter les dropdowns de la modale frontend."""
    return AutoUploadMeta(
        document_types=_DOCUMENT_TYPES,
        entity_types=_ENTITY_TYPES,
        overwrite_strategies=_OVERWRITE_STRATEGIES,
    )


# ---------------------------------------------------------------------------
# Routes — CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=list[DriveAutoUploadRead])
async def list_auto_uploads(
    db: DBSession,
    user: RequireAdminOrOwner,
    document_type: Optional[str] = Query(default=None, max_length=64),
    entity_type: Optional[str] = Query(default=None, max_length=64),
    active: Optional[bool] = Query(default=None),
) -> list[DriveAutoUploadRead]:
    """Liste les règles, filtrables par type de document / entité / actif."""
    stmt = select(DriveAutoUpload).order_by(DriveAutoUpload.id.asc())
    if document_type is not None:
        stmt = stmt.where(DriveAutoUpload.document_type == document_type)
    if entity_type is not None:
        stmt = stmt.where(DriveAutoUpload.entity_type == entity_type)
    if active is not None:
        stmt = stmt.where(DriveAutoUpload.active == active)
    rows = (await db.execute(stmt)).scalars().all()
    return [DriveAutoUploadRead.model_validate(r) for r in rows]


@router.get("/{rule_id}", response_model=DriveAutoUploadRead)
async def get_auto_upload(
    rule_id: int, db: DBSession, user: RequireAdminOrOwner
) -> DriveAutoUploadRead:
    rule = await db.get(DriveAutoUpload, rule_id)
    if rule is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Règle #{rule_id} introuvable."
        )
    return DriveAutoUploadRead.model_validate(rule)


@router.post(
    "", response_model=DriveAutoUploadRead, status_code=status.HTTP_201_CREATED
)
async def create_auto_upload(
    db: DBSession,
    user: RequireAdminOrOwner,
    payload: DriveAutoUploadCreate = Body(...),
) -> DriveAutoUploadRead:
    """Crée une nouvelle règle. Posée inactive par défaut."""
    rule = DriveAutoUpload(
        name=payload.name,
        document_type=payload.document_type,
        entity_type=payload.entity_type,
        subfolder_path_template=payload.subfolder_path_template,
        file_name_template=payload.file_name_template,
        overwrite_strategy=payload.overwrite_strategy,
        active=payload.active,
        description=payload.description,
        created_by_user_id=user.id,
    )
    db.add(rule)
    await db.flush()
    await log_action(
        db,
        user=user,
        action="drive_auto_upload.create",
        entity_type="drive_auto_upload",
        entity_id=rule.id,
        details={
            "name": rule.name,
            "document_type": rule.document_type,
            "entity_type": rule.entity_type,
            "active": rule.active,
        },
    )
    await db.commit()
    await db.refresh(rule)
    return DriveAutoUploadRead.model_validate(rule)


@router.patch("/{rule_id}", response_model=DriveAutoUploadRead)
async def patch_auto_upload(
    rule_id: int,
    db: DBSession,
    user: RequireAdminOrOwner,
    payload: DriveAutoUploadPatch = Body(...),
) -> DriveAutoUploadRead:
    """Met à jour les champs présents (toggle actif, templates, stratégie)."""
    rule = await db.get(DriveAutoUpload, rule_id)
    if rule is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Règle #{rule_id} introuvable."
        )

    changes: dict[str, object] = {}
    data = payload.model_dump(exclude_unset=True)
    for field in (
        "name",
        "subfolder_path_template",
        "file_name_template",
        "overwrite_strategy",
        "active",
        "description",
    ):
        if field in data:
            setattr(rule, field, data[field])
            changes[field] = data[field]

    await db.flush()
    await log_action(
        db,
        user=user,
        action="drive_auto_upload.update",
        entity_type="drive_auto_upload",
        entity_id=rule.id,
        details={"changes": list(changes)},
    )
    await db.commit()
    await db.refresh(rule)
    return DriveAutoUploadRead.model_validate(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_auto_upload(
    rule_id: int, db: DBSession, user: RequireAdminOrOwner
) -> None:
    """Soft-delete : positionne ``active=False`` (préserve l'historique)."""
    rule = await db.get(DriveAutoUpload, rule_id)
    if rule is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Règle #{rule_id} introuvable."
        )
    rule.active = False
    await db.flush()
    await log_action(
        db,
        user=user,
        action="drive_auto_upload.soft_delete",
        entity_type="drive_auto_upload",
        entity_id=rule.id,
        details={"name": rule.name},
    )
    await db.commit()
