"""Endpoints REST Google Drive — Phase 2.

Tous protégés par :data:`RequireAdminOrOwner`. Toutes les opérations
sont déléguées au wrapper :mod:`app.services.drive_api`, qui gère
l'audit log et la traduction des erreurs Google.
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Body,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response

from app.api.deps import DBSession, RequireAdminOrOwner
from app.schemas.drive import (
    DriveCopyFolderRequest,
    DriveCreateFolderRequest,
    DriveFile,
    DriveFilePatch,
    DriveFolderContents,
    DriveFolderPath,
    DriveFolderPathSegment,
    DrivePermission,
    DrivePermissionList,
    DrivePreviewUrl,
    DriveSearchResult,
    DriveShareRequest,
    normalize_drive_file,
)
from app.services import drive_api
from app.services.drive_exceptions import (
    DriveAPIError,
    DriveAuthError,
    DriveError,
    DriveExportRequired,
    DriveNotFoundError,
    DrivePermissionError,
    DriveQuotaExceeded,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/drive", tags=["drive-files"])


# ---------------------------------------------------------------------------
# Translation exceptions → HTTPException
# ---------------------------------------------------------------------------


def _raise_for_drive(exc: DriveError) -> None:
    """Mappe une exception Drive custom vers une HTTPException FastAPI."""
    if isinstance(exc, DriveAuthError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.message)
    if isinstance(exc, DriveNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    if isinstance(exc, DrivePermissionError):
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message)
    if isinstance(exc, DriveExportRequired):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": exc.message,
                "export_mime_types": exc.export_mime_types,
                "file_id": exc.file_id,
            },
        )
    if isinstance(exc, DriveQuotaExceeded):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, exc.message)
    # DriveAPIError ou DriveError nu → 502.
    raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.message)


# ---------------------------------------------------------------------------
# Préfixes MIME pour /export
# ---------------------------------------------------------------------------

# Map UX format → MIME Google (utilisé sur /export?format=pdf).
_EXPORT_FORMATS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "csv": "text/csv",
    "html": "text/html",
}

_EXPORT_EXTENSIONS = {v: k for k, v in _EXPORT_FORMATS.items()}


# ---------------------------------------------------------------------------
# Listing & métadonnées
# ---------------------------------------------------------------------------


@router.get(
    "/folders/{folder_id}/files",
    response_model=DriveFolderContents,
)
async def list_folder_files(
    folder_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
    page_size: int = Query(100, ge=1, le=1000),
    page_token: Optional[str] = None,
    order_by: str = "folder,name",
) -> DriveFolderContents:
    """Liste le contenu d'un dossier Drive."""
    try:
        result = await drive_api.list_folder_contents(
            user.id,
            db,
            folder_id,
            page_size=page_size,
            page_token=page_token,
            order_by=order_by,
        )
    except DriveError as exc:
        _raise_for_drive(exc)
    return DriveFolderContents(
        files=[normalize_drive_file(f) for f in result["files"]],
        next_page_token=result.get("next_page_token"),
    )


@router.get(
    "/files/{file_id}/metadata",
    response_model=DriveFile,
)
async def get_metadata(
    file_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> DriveFile:
    """Métadonnées complètes d'un fichier."""
    try:
        meta = await drive_api.get_file_metadata(user.id, db, file_id)
    except DriveError as exc:
        _raise_for_drive(exc)
    return normalize_drive_file(meta)


@router.get(
    "/folders/{folder_id}/path",
    response_model=DriveFolderPath,
)
async def get_folder_path(
    folder_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> DriveFolderPath:
    """Chaîne de breadcrumbs racine → dossier courant."""
    try:
        segments = await drive_api.get_folder_path(user.id, db, folder_id)
    except DriveError as exc:
        _raise_for_drive(exc)
    return DriveFolderPath(
        segments=[
            DriveFolderPathSegment(id=s["id"], name=s["name"])
            for s in segments
        ]
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@router.post(
    "/folders/{folder_id}/upload",
    response_model=DriveFile,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    folder_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
    file: UploadFile = File(...),
) -> DriveFile:
    """Upload multipart d'un fichier dans le dossier ``folder_id``."""
    contents = await file.read()
    try:
        created = await drive_api.upload_file(
            user.id,
            db,
            parent_folder_id=folder_id,
            file_name=file.filename or "uploaded",
            file_bytes=contents,
            mime_type=file.content_type or None,
        )
    except DriveError as exc:
        _raise_for_drive(exc)
    return normalize_drive_file(created)


# ---------------------------------------------------------------------------
# Download / Export / Preview
# ---------------------------------------------------------------------------


def _content_disposition(filename: str) -> str:
    """Header RFC 5987 avec fallback ASCII pour les noms accentués."""
    quoted = quote(filename, safe="")
    return f"attachment; filename*=UTF-8''{quoted}"


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> Response:
    """Stream binaire brut. 409 si fichier Google natif (utiliser /export)."""
    try:
        meta = await drive_api.get_file_metadata(user.id, db, file_id)
        payload = await drive_api.download_file(user.id, db, file_id)
    except DriveError as exc:
        _raise_for_drive(exc)
    return Response(
        content=payload,
        media_type=meta.get("mimeType") or "application/octet-stream",
        headers={
            "Content-Disposition": _content_disposition(
                meta.get("name") or "download"
            )
        },
    )


@router.get("/files/{file_id}/export")
async def export_file(
    file_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
    format: str = Query("pdf", min_length=2, max_length=8),
) -> Response:
    """Exporte un Google Doc / Sheet / Slide vers PDF / DOCX / XLSX / PPTX."""
    export_mime = _EXPORT_FORMATS.get(format.lower())
    if not export_mime:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Format export inconnu : {format}. "
            f"Accepté : {', '.join(_EXPORT_FORMATS)}.",
        )
    try:
        meta = await drive_api.get_file_metadata(user.id, db, file_id)
        payload = await drive_api.export_google_doc(
            user.id, db, file_id, export_mime
        )
    except DriveError as exc:
        _raise_for_drive(exc)
    base_name = meta.get("name") or "export"
    file_name = f"{base_name}.{format.lower()}"
    return Response(
        content=payload,
        media_type=export_mime,
        headers={"Content-Disposition": _content_disposition(file_name)},
    )


@router.get("/files/{file_id}/preview-url", response_model=DrivePreviewUrl)
async def get_preview_url(
    file_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> DrivePreviewUrl:
    """URL ``drive.google.com/file/d/{id}/preview`` (iframe-friendly).

    On valide d'abord l'accès via une lecture metadata — sinon on
    retournerait une URL morte côté UI.
    """
    try:
        meta = await drive_api.get_file_metadata(user.id, db, file_id)
    except DriveError as exc:
        _raise_for_drive(exc)
    return DrivePreviewUrl(
        preview_url=f"https://drive.google.com/file/d/{file_id}/preview",
        web_view_link=meta.get("webViewLink"),
    )


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


@router.patch("/files/{file_id}", response_model=DriveFile)
async def patch_file(
    file_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
    payload: DriveFilePatch = Body(...),
) -> DriveFile:
    """Renomme et/ou déplace selon les champs présents."""
    if payload.name is None and payload.parent_folder_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Au moins un de `name` ou `parent_folder_id` est requis.",
        )
    try:
        result: dict
        if payload.name is not None:
            result = await drive_api.rename_file(
                user.id, db, file_id, payload.name
            )
        if payload.parent_folder_id is not None:
            result = await drive_api.move_file(
                user.id,
                db,
                file_id,
                payload.parent_folder_id,
                old_parent_folder_id=payload.old_parent_folder_id,
            )
    except DriveError as exc:
        _raise_for_drive(exc)
    return normalize_drive_file(result)


@router.delete(
    "/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_file(
    file_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
    permanent: bool = Query(default=False),
) -> None:
    """Trash par défaut. ``?permanent=true`` pour suppression définitive."""
    try:
        if permanent:
            await drive_api.delete_file_permanent(user.id, db, file_id)
        else:
            await drive_api.trash_file(user.id, db, file_id)
    except DriveError as exc:
        _raise_for_drive(exc)


@router.post(
    "/files/{file_id}/restore",
    response_model=DriveFile,
)
async def restore_file(
    file_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> DriveFile:
    """Restaure depuis la corbeille."""
    try:
        restored = await drive_api.restore_from_trash(user.id, db, file_id)
    except DriveError as exc:
        _raise_for_drive(exc)
    return normalize_drive_file(restored)


# ---------------------------------------------------------------------------
# Dossiers
# ---------------------------------------------------------------------------


@router.post(
    "/folders/{folder_id}/subfolders",
    response_model=DriveFile,
    status_code=status.HTTP_201_CREATED,
)
async def create_subfolder(
    folder_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
    payload: DriveCreateFolderRequest = Body(...),
) -> DriveFile:
    """Crée un sous-dossier dans ``folder_id``."""
    try:
        created = await drive_api.create_folder(
            user.id, db, folder_id, payload.name
        )
    except DriveError as exc:
        _raise_for_drive(exc)
    return normalize_drive_file(created)


@router.post(
    "/folders/{source_folder_id}/copy",
    response_model=DriveFile,
    status_code=status.HTTP_201_CREATED,
)
async def copy_folder(
    source_folder_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
    payload: DriveCopyFolderRequest = Body(...),
) -> DriveFile:
    """Copie récursive d'un dossier (limite profondeur 5)."""
    try:
        new_folder = await drive_api.copy_folder_recursive(
            user.id,
            db,
            source_folder_id,
            payload.parent_folder_id,
            new_name=payload.new_name,
        )
    except DriveError as exc:
        _raise_for_drive(exc)
    return normalize_drive_file(new_folder)


# ---------------------------------------------------------------------------
# Recherche
# ---------------------------------------------------------------------------


@router.get("/search", response_model=DriveSearchResult)
async def search(
    db: DBSession,
    user: RequireAdminOrOwner,
    q: str = Query(..., min_length=1, max_length=200),
    parent_folder_id: Optional[str] = None,
    page_size: int = Query(50, ge=1, le=200),
) -> DriveSearchResult:
    """Cherche par nom ou contenu (optionnellement restreint à un dossier)."""
    try:
        result = await drive_api.search_files(
            user.id,
            db,
            q,
            parent_folder_id=parent_folder_id,
            page_size=page_size,
        )
    except DriveError as exc:
        _raise_for_drive(exc)
    return DriveSearchResult(
        files=[normalize_drive_file(f) for f in result["files"]],
        next_page_token=result.get("next_page_token"),
    )


# ---------------------------------------------------------------------------
# Partage
# ---------------------------------------------------------------------------


@router.get(
    "/files/{file_id}/permissions",
    response_model=DrivePermissionList,
)
async def list_file_permissions(
    file_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> DrivePermissionList:
    """Liste les permissions actuelles."""
    try:
        perms = await drive_api.list_permissions(user.id, db, file_id)
    except DriveError as exc:
        _raise_for_drive(exc)
    return DrivePermissionList(
        permissions=[DrivePermission.model_validate(p) for p in perms]
    )


@router.post(
    "/files/{file_id}/share",
    response_model=DrivePermission,
    status_code=status.HTTP_201_CREATED,
)
async def share_file(
    file_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
    payload: DriveShareRequest = Body(...),
) -> DrivePermission:
    """Partage le fichier avec ``email`` au rôle demandé."""
    try:
        permission = await drive_api.share_file(
            user.id,
            db,
            file_id,
            payload.email,
            role=payload.role,
            send_notification=payload.send_notification,
            message=payload.message,
        )
    except DriveError as exc:
        _raise_for_drive(exc)
    return DrivePermission.model_validate(permission)


@router.delete(
    "/files/{file_id}/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_file_permission(
    file_id: str,
    permission_id: str,
    db: DBSession,
    user: RequireAdminOrOwner,
) -> None:
    """Révoque une permission."""
    try:
        await drive_api.revoke_permission(user.id, db, file_id, permission_id)
    except DriveError as exc:
        _raise_for_drive(exc)
