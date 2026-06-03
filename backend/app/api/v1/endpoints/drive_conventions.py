"""Endpoints REST Drive Conventions et Entity Links — Phase 4.

Tous protégés par :data:`RequireAdminOrOwner`. Les mutations posent
un audit log (table générique ``audit_logs``, distinct du
``drive_audit_logs`` qui sert aux opérations Drive directes — ici on
parle d'opérations de CONFIGURATION).

Surface :

**Conventions CRUD**

- ``GET    /api/v1/drive/conventions`` — liste avec filtres
  ``entity_type``, ``active``.
- ``GET    /api/v1/drive/conventions/{id}``
- ``POST   /api/v1/drive/conventions``
- ``PATCH  /api/v1/drive/conventions/{id}``
- ``DELETE /api/v1/drive/conventions/{id}`` — soft delete via
  ``active=False`` (préserve les ``DriveEntityLink`` qui pointent
  vers cette convention).

**Action manuelle**

- ``POST /api/v1/drive/conventions/{id}/apply`` — applique la
  convention à une entité existante.

**Métadonnées**

- ``GET /api/v1/drive/conventions/supported-entity-types`` (legacy)
- ``GET /api/v1/drive/entity-catalog`` — catalogue COMPLET introspecté
  des types linkables + leurs champs (alimente la modale dynamique).

**Entity links**

- ``GET    /api/v1/drive/entity-links`` — filtres ``entity_type``,
  ``entity_id``.
- ``POST   /api/v1/drive/entity-links`` — lien manuel sans convention.
- ``PATCH  /api/v1/drive/entity-links/{id}`` — re-cible le lien vers un
  autre dossier Drive ("changer de dossier").
- ``DELETE /api/v1/drive/entity-links/{id}`` — supprime le lien
  Kratos-side seulement (le dossier Drive reste intact).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DBSession, RequireAdminOrOwner
from app.models.drive_convention import DriveConvention
from app.models.drive_entity_link import DriveEntityLink
from app.schemas.drive_convention import (
    DriveConventionApplyRequest,
    DriveConventionApplyResult,
    DriveConventionCreate,
    DriveConventionPatch,
    DriveConventionRead,
    DriveEntityLinkCreate,
    DriveEntityLinkPatch,
    DriveEntityLinkRead,
    EntityCatalogType,
    SupportedEntityType,
)
from app.services import drive_conventions_engine as engine
from app.services.audit import log_action
from app.services.drive_exceptions import (
    DriveAuthError,
    DriveError,
    DriveNotFoundError,
    DrivePermissionError,
    DriveQuotaExceeded,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/drive", tags=["drive-conventions"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raise_for_engine(exc: engine.ConventionEngineError) -> None:
    """Mappe les exceptions du moteur vers HTTPException."""
    if isinstance(exc, engine.ConventionNotFound):
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, engine.EntityNotFound):
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, engine.EntityAlreadyLinked):
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, engine.UnsupportedEntityType):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, engine.ConventionMisconfigured):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))


def _raise_for_drive(exc: DriveError) -> None:
    """Mappe les exceptions Drive vers HTTPException (cf. drive_files.py)."""
    if isinstance(exc, DriveAuthError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.message)
    if isinstance(exc, DriveNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    if isinstance(exc, DrivePermissionError):
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message)
    if isinstance(exc, DriveQuotaExceeded):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, exc.message)
    raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.message)


# ---------------------------------------------------------------------------
# Conventions — CRUD
# ---------------------------------------------------------------------------


# IMPORTANT : les routes littérales ``/conventions/supported-entity-types``
# et ``/entity-catalog`` doivent être déclarées AVANT la route à param
# ``/conventions/{convention_id}`` pour ne pas se faire intercepter par
# FastAPI (qui tenterait de parser le segment littéral en int).


@router.get(
    "/conventions/supported-entity-types",
    response_model=list[SupportedEntityType],
)
async def list_supported_entity_types(
    user: RequireAdminOrOwner,
) -> list[SupportedEntityType]:
    """Métadonnées (legacy) pour alimenter les dropdowns du wizard."""
    raw = await engine.get_supported_entity_types()
    return [SupportedEntityType.model_validate(item) for item in raw]


@router.get(
    "/entity-catalog",
    response_model=list[EntityCatalogType],
)
async def get_entity_catalog(
    user: RequireAdminOrOwner,
) -> list[EntityCatalogType]:
    """Catalogue COMPLET des types d'entités linkables + leurs champs.

    Introspecte les colonnes des modèles SQLAlchemy déclarés et expose,
    pour chaque type, la liste des champs (``path``/``label``/``type``)
    insérables comme placeholders ``{path}`` dans le pattern de nommage.
    Alimente la modale dynamique de création de convention.
    """
    raw = engine.get_entity_catalog()
    return [EntityCatalogType.model_validate(item) for item in raw]


@router.get(
    "/conventions",
    response_model=list[DriveConventionRead],
)
async def list_conventions(
    db: DBSession,
    user: RequireAdminOrOwner,
    entity_type: Optional[str] = Query(default=None, max_length=64),
    active: Optional[bool] = Query(default=None),
) -> list[DriveConventionRead]:
    """Liste les conventions, filtrables par type d'entité et actif."""
    stmt = select(DriveConvention).order_by(
        DriveConvention.priority.desc(), DriveConvention.id.asc()
    )
    if entity_type is not None:
        stmt = stmt.where(DriveConvention.entity_type == entity_type)
    if active is not None:
        stmt = stmt.where(DriveConvention.active == active)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [DriveConventionRead.model_validate(row) for row in rows]


@router.get(
    "/conventions/{convention_id}",
    response_model=DriveConventionRead,
)
async def get_convention(
    convention_id: int,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> DriveConventionRead:
    convention = await db.get(DriveConvention, convention_id)
    if convention is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Convention #{convention_id} introuvable."
        )
    return DriveConventionRead.model_validate(convention)


@router.post(
    "/conventions",
    response_model=DriveConventionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_convention(
    db: DBSession,
    user: RequireAdminOrOwner,
    payload: DriveConventionCreate = Body(...),
) -> DriveConventionRead:
    """Crée une nouvelle convention. Posée inactive par défaut."""
    try:
        payload = payload.validated()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    convention = DriveConvention(
        name=payload.name,
        entity_type=payload.entity_type,
        trigger_event=payload.trigger_event,
        parent_folder_drive_id=payload.parent_folder_drive_id,
        folder_name_template=payload.folder_name_template,
        template_folder_to_copy_drive_id=payload.template_folder_to_copy_drive_id,
        subfolders_to_create=payload.subfolders_to_create,
        variable_mapping=payload.variable_mapping,
        auto_link_to_entity=payload.auto_link_to_entity,
        status_to_parent_map=payload.status_to_parent_map,
        active=payload.active,
        priority=payload.priority,
        description=payload.description,
        created_by_user_id=user.id,
    )
    db.add(convention)
    await db.flush()

    await log_action(
        db,
        user=user,
        action="drive_convention.create",
        entity_type="drive_convention",
        entity_id=convention.id,
        details={
            "name": convention.name,
            "entity_type": convention.entity_type,
            "active": convention.active,
        },
    )
    await db.commit()
    await db.refresh(convention)
    return DriveConventionRead.model_validate(convention)


@router.patch(
    "/conventions/{convention_id}",
    response_model=DriveConventionRead,
)
async def patch_convention(
    convention_id: int,
    db: DBSession,
    user: RequireAdminOrOwner,
    payload: DriveConventionPatch = Body(...),
) -> DriveConventionRead:
    """Met à jour les champs présents — tous les autres restent intacts."""
    try:
        payload = payload.validated()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    convention = await db.get(DriveConvention, convention_id)
    if convention is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Convention #{convention_id} introuvable."
        )

    changes: dict[str, object] = {}
    for field in (
        "name",
        "entity_type",
        "trigger_event",
        "parent_folder_drive_id",
        "folder_name_template",
        "template_folder_to_copy_drive_id",
        "subfolders_to_create",
        "variable_mapping",
        "auto_link_to_entity",
        "status_to_parent_map",
        "active",
        "priority",
        "description",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(convention, field, value)
            changes[field] = value

    await db.flush()
    await log_action(
        db,
        user=user,
        action="drive_convention.update",
        entity_type="drive_convention",
        entity_id=convention.id,
        details={"changes": list(changes)},
    )
    await db.commit()
    await db.refresh(convention)
    return DriveConventionRead.model_validate(convention)


@router.delete(
    "/conventions/{convention_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_convention(
    convention_id: int,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> None:
    """Soft-delete : positionne ``active=False``.

    On ne fait PAS de DELETE physique pour préserver les
    ``DriveEntityLink`` créés via cette convention (le champ
    ``convention_id`` reste vivant en BDD pour l'historique).
    """
    convention = await db.get(DriveConvention, convention_id)
    if convention is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Convention #{convention_id} introuvable."
        )
    convention.active = False
    await db.flush()
    await log_action(
        db,
        user=user,
        action="drive_convention.soft_delete",
        entity_type="drive_convention",
        entity_id=convention.id,
        details={"name": convention.name},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Action ``apply``
# ---------------------------------------------------------------------------


def _drive_folder_url(folder_id: Optional[str]) -> Optional[str]:
    if not folder_id:
        return None
    return f"https://drive.google.com/drive/folders/{folder_id}"


def _resolved_subfolders(spec: object) -> list[str]:
    if not isinstance(spec, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in spec:
        if not raw:
            continue
        name = str(raw).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


@router.post(
    "/conventions/{convention_id}/apply",
    response_model=DriveConventionApplyResult,
)
async def apply_convention(
    convention_id: int,
    db: DBSession,
    user: RequireAdminOrOwner,
    payload: DriveConventionApplyRequest = Body(...),
) -> DriveConventionApplyResult:
    """Applique manuellement la convention à une entité existante.

    Crée le dossier Drive (copie template ou création vide), les
    sous-dossiers, et persiste le :class:`DriveEntityLink`. Retourne
    le lien créé + métadonnées d'affichage (sous-dossiers, URL Drive).
    """
    # Pré-charge pour récupérer la liste résolue des sous-dossiers à
    # afficher dans la réponse (le moteur lui-même n'expose pas ce
    # détail, mais Phil veut le voir dans l'UI confirmation).
    convention = await db.get(DriveConvention, convention_id)
    if convention is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Convention #{convention_id} introuvable."
        )

    try:
        link = await engine.apply_convention_to_entity(
            convention_id=convention_id,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            user_id=user.id,
            db=db,
        )
    except engine.ConventionEngineError as exc:
        _raise_for_engine(exc)
    except DriveError as exc:  # type: ignore[misc]  # subclass d'Exception
        _raise_for_drive(exc)

    await log_action(
        db,
        user=user,
        action="drive_convention.apply",
        entity_type="drive_convention",
        entity_id=convention_id,
        details={
            "target_entity_type": payload.entity_type,
            "target_entity_id": payload.entity_id,
            "drive_folder_id": link.drive_folder_id,
            "drive_folder_name": link.drive_folder_name,
        },
    )
    await db.commit()
    await db.refresh(link)

    return DriveConventionApplyResult(
        link=DriveEntityLinkRead.model_validate(link),
        subfolders_created=_resolved_subfolders(
            convention.subfolders_to_create
        ),
        drive_folder_url=_drive_folder_url(link.drive_folder_id),
    )


# ---------------------------------------------------------------------------
# Entity links — CRUD minimal
# ---------------------------------------------------------------------------


@router.get(
    "/entity-links",
    response_model=list[DriveEntityLinkRead],
)
async def list_entity_links(
    db: DBSession,
    user: RequireAdminOrOwner,
    entity_type: Optional[str] = Query(default=None, max_length=64),
    # ge=0 : entity_id=0 filtre les liens "Drive de page" (singleton).
    entity_id: Optional[int] = Query(default=None, ge=0),
) -> list[DriveEntityLinkRead]:
    """Liste les liens entité ↔ Drive. Filtres optionnels."""
    stmt = select(DriveEntityLink).order_by(DriveEntityLink.created_at.desc())
    if entity_type is not None:
        stmt = stmt.where(DriveEntityLink.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(DriveEntityLink.entity_id == entity_id)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [DriveEntityLinkRead.model_validate(r) for r in rows]


@router.post(
    "/entity-links",
    response_model=DriveEntityLinkRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_entity_link(
    db: DBSession,
    user: RequireAdminOrOwner,
    payload: DriveEntityLinkCreate = Body(...),
) -> DriveEntityLinkRead:
    """Crée un lien manuel entité ↔ dossier Drive existant.

    Sert à rattacher un dossier déjà créé dans Drive (hors Kratos) à
    une entité Kratos sans passer par le moteur de convention.

    Conflit : si un lien existe déjà pour ``(entity_type, entity_id)``,
    on retourne 409. C'est la même règle que le moteur — éviter
    qu'une entité pointe vers deux dossiers Drive différents.
    """
    stmt = select(DriveEntityLink).where(
        DriveEntityLink.entity_type == payload.entity_type,
        DriveEntityLink.entity_id == payload.entity_id,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Un lien Drive existe déjà pour {payload.entity_type}"
            f"#{payload.entity_id} (lien #{existing.id}).",
        )

    link = DriveEntityLink(
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        drive_folder_id=payload.drive_folder_id,
        drive_folder_name=payload.drive_folder_name,
        created_by_user_id=user.id,
    )
    db.add(link)
    await db.flush()
    await log_action(
        db,
        user=user,
        action="drive_entity_link.create",
        entity_type="drive_entity_link",
        entity_id=link.id,
        details={
            "target_entity_type": payload.entity_type,
            "target_entity_id": payload.entity_id,
            "drive_folder_id": payload.drive_folder_id,
        },
    )
    await db.commit()
    await db.refresh(link)
    return DriveEntityLinkRead.model_validate(link)


@router.patch(
    "/entity-links/{link_id}",
    response_model=DriveEntityLinkRead,
)
async def patch_entity_link(
    link_id: int,
    db: DBSession,
    user: RequireAdminOrOwner,
    payload: DriveEntityLinkPatch = Body(...),
) -> DriveEntityLinkRead:
    """Re-cible un lien existant vers un autre dossier Drive.

    Cas d'usage : un mauvais dossier a été lié à l'entité et on veut
    corriger la liaison sans la recréer. La cible Kratos
    (``entity_type``/``entity_id``) reste inchangée ; seul le dossier
    Drive pointé change. Le dossier Drive précédent reste intact.
    """
    link = await db.get(DriveEntityLink, link_id)
    if link is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Lien #{link_id} introuvable."
        )

    old_folder_id = link.drive_folder_id
    new_folder_id = (payload.drive_folder_id or "").strip()
    if not new_folder_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "drive_folder_id requis."
        )

    link.drive_folder_id = new_folder_id
    if payload.drive_folder_name is not None:
        cleaned_name = payload.drive_folder_name.strip()
        link.drive_folder_name = cleaned_name or None
    # Le lien n'est plus issu d'une convention une fois re-ciblé à la main.
    link.convention_id = None

    await db.flush()
    await log_action(
        db,
        user=user,
        action="drive_entity_link.relinked",
        entity_type="drive_entity_link",
        entity_id=link.id,
        details={
            "target_entity_type": link.entity_type,
            "target_entity_id": link.entity_id,
            "old_drive_folder_id": old_folder_id,
            "new_drive_folder_id": new_folder_id,
        },
    )
    await db.commit()
    await db.refresh(link)
    return DriveEntityLinkRead.model_validate(link)


@router.delete(
    "/entity-links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_entity_link(
    link_id: int,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> None:
    """Supprime le lien côté Kratos. Le dossier Drive reste intact."""
    link = await db.get(DriveEntityLink, link_id)
    if link is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Lien #{link_id} introuvable."
        )
    snapshot = {
        "target_entity_type": link.entity_type,
        "target_entity_id": link.entity_id,
        "drive_folder_id": link.drive_folder_id,
    }
    await db.delete(link)
    await db.flush()
    await log_action(
        db,
        user=user,
        action="drive_entity_link.delete",
        entity_type="drive_entity_link",
        entity_id=link_id,
        details=snapshot,
    )
    await db.commit()
