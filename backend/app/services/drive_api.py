"""Google Drive API wrapper — Phase 2.

Surface complète des opérations CRUD Drive utilisée par Kratos :
listing, upload, download, mutations, dossiers, recherche, partage.

Toutes les fonctions :

- prennent un ``user_id`` Kratos en premier argument ;
- récupèrent un access_token valide via
  :func:`app.services.drive_oauth.get_valid_access_token`
  (refresh automatique si proche d'expirer) ;
- déclenchent un audit log dans ``drive_audit_logs`` (succès et échec) ;
- traduisent les erreurs Google en exceptions custom typées
  (cf. :mod:`app.services.drive_exceptions`).

Le wrapper n'est PAS asynchrone côté Google : ``google-api-python-client``
est synchrone. On exécute les appels Drive via ``asyncio.to_thread`` pour
ne pas bloquer la boucle FastAPI.

Aucun cache local : la source de vérité reste Google Drive. Les pages
Kratos qui veulent éviter de retaper l'API à chaque rendu utilisent la
table ``drive_entity_links`` (cf. Phase 4).
"""

from __future__ import annotations

import asyncio
import io
import logging
import mimetypes
from typing import Any, Optional

from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2.credentials import Credentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_audit_log import DriveAuditLog
from app.services import drive_oauth
from app.services.drive_exceptions import (
    DriveAPIError,
    DriveAuthError,
    DriveExportRequired,
    DriveNotFoundError,
    DrivePermissionError,
    DriveQuotaExceeded,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Champs renvoyés par Drive pour les fichiers (utilisés dans `fields`).
_FILE_FIELDS = (
    "id, name, mimeType, size, modifiedTime, createdTime, "
    "owners(displayName,emailAddress), parents, thumbnailLink, "
    "webViewLink, iconLink, trashed"
)
_LIST_FIELDS = f"nextPageToken, files({_FILE_FIELDS})"

# MIME types Google natifs (doivent passer par /export, pas /download).
_GOOGLE_NATIVE_MIMES = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
    "application/vnd.google-apps.drawing",
    "application/vnd.google-apps.form",
    "application/vnd.google-apps.script",
}

# Format MIME des dossiers Drive (constant Google).
FOLDER_MIME = "application/vnd.google-apps.folder"

# Profondeur max pour copy_folder_recursive (protection anti-boucle infinie).
_MAX_COPY_DEPTH = 5


# ---------------------------------------------------------------------------
# Audit helper (mutualise le pattern drive_audit_logs)
# ---------------------------------------------------------------------------


async def _audit(
    db: AsyncSession,
    *,
    user_id: Optional[int],
    google_email: Optional[str],
    action: str,
    drive_file_id: Optional[str] = None,
    drive_file_name: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
    success: bool = True,
    error_message: Optional[str] = None,
) -> None:
    try:
        entry = DriveAuditLog(
            user_id=user_id,
            google_email=google_email,
            action=action,
            drive_file_id=drive_file_id,
            drive_file_name=drive_file_name,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            success=success,
            error_message=error_message,
        )
        db.add(entry)
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        log.warning("drive audit log failed for %s: %s", action, exc)


# ---------------------------------------------------------------------------
# Construction du service Drive
# ---------------------------------------------------------------------------


def _build_service_sync(access_token: str) -> Resource:
    """Construit le client Drive v3 à partir d'un access_token."""
    creds = Credentials(token=access_token)
    # cache_discovery=False — évite un warning bruyant et un fichier cache
    # local inutile sur Render (FS éphémère).
    return build("drive", "v3", credentials=creds, cache_discovery=False)


async def get_drive_service(
    user_id: int, db: AsyncSession
) -> Resource:
    """Retourne un client Drive API v3 authentifié pour cet utilisateur.

    Récupère un access_token via :mod:`drive_oauth` (refresh auto).
    Lève :class:`DriveAuthError` si l'utilisateur n'a pas de connexion
    Drive valide.
    """
    access_token = await drive_oauth.get_valid_access_token(
        db, user_id=user_id
    )
    if not access_token:
        raise DriveAuthError(
            "Connecte d'abord ton compte Google Drive dans Paramètres."
        )
    return await asyncio.to_thread(_build_service_sync, access_token)


# ---------------------------------------------------------------------------
# Traduction HttpError → exceptions custom
# ---------------------------------------------------------------------------


def _translate_http_error(exc: HttpError, *, file_id: str | None = None) -> Exception:
    """Mappe une HttpError Google vers nos exceptions custom."""
    status_code = getattr(exc, "status_code", None) or getattr(
        exc.resp, "status", None
    )
    try:
        status_int = int(status_code) if status_code is not None else 0
    except (TypeError, ValueError):
        status_int = 0

    detail = ""
    try:
        detail = exc._get_reason() or ""  # noqa: SLF001
    except Exception:  # noqa: BLE001
        detail = str(exc)

    if status_int == 401:
        return DriveAuthError(
            "Session Google expirée. Reconnecte ton compte Drive dans Paramètres.",
            original=exc,
        )
    if status_int == 403:
        # Quota épuisé vs permission refusée — Google distingue par le
        # reason dans le payload JSON.
        lowered = detail.lower()
        if "quota" in lowered or "ratelimit" in lowered or "userratelimit" in lowered:
            return DriveQuotaExceeded(
                "Quota Google Drive dépassé. Réessaye dans quelques minutes.",
                original=exc,
            )
        return DrivePermissionError(
            "Google Drive a refusé cette opération (permissions insuffisantes).",
            original=exc,
        )
    if status_int == 404:
        return DriveNotFoundError(
            f"Fichier ou dossier Drive introuvable{f' ({file_id})' if file_id else ''}.",
            original=exc,
        )
    if status_int == 429:
        return DriveQuotaExceeded(
            "Trop de requêtes vers Google Drive. Réessaye dans quelques secondes.",
            original=exc,
        )
    return DriveAPIError(
        f"Erreur Google Drive (HTTP {status_int}): {detail or 'inconnue'}.",
        original=exc,
    )


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------


def _strip_user_id(file_obj: dict[str, Any]) -> dict[str, Any]:
    """Garde les champs utiles côté client, normalise quelques absents."""
    file_obj.setdefault("parents", [])
    return file_obj


async def _google_email_for(
    user_id: int, db: AsyncSession
) -> Optional[str]:
    try:
        return await drive_oauth.get_user_email(db, user_id=user_id)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Listing & métadonnées
# ---------------------------------------------------------------------------


async def list_folder_contents(
    user_id: int,
    db: AsyncSession,
    folder_id: str,
    *,
    page_size: int = 100,
    page_token: Optional[str] = None,
    order_by: str = "folder,name",
) -> dict[str, Any]:
    """Liste le contenu d'un dossier (non-trashed). Pagination Google."""
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    # Query Drive : enfants directs du dossier, non corbeille.
    query = f"'{folder_id}' in parents and trashed = false"
    try:
        result = await asyncio.to_thread(
            lambda: service.files().list(
                q=query,
                pageSize=page_size,
                pageToken=page_token,
                orderBy=order_by,
                fields=_LIST_FIELDS,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=folder_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="list_folder",
            drive_file_id=folder_id,
            success=False,
            error_message=str(translated),
        )
        raise translated from exc

    files = [_strip_user_id(f) for f in result.get("files", [])]
    next_page_token = result.get("nextPageToken")
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="list_folder",
        drive_file_id=folder_id,
        details={"count": len(files), "page_token": page_token},
    )
    return {"files": files, "next_page_token": next_page_token}


async def get_file_metadata(
    user_id: int, db: AsyncSession, file_id: str
) -> dict[str, Any]:
    """Métadonnées complètes (incluant parents pour breadcrumbs)."""
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    try:
        meta = await asyncio.to_thread(
            lambda: service.files().get(
                fileId=file_id,
                fields=_FILE_FIELDS,
                supportsAllDrives=True,
            ).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=file_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="get_metadata",
            drive_file_id=file_id,
            success=False,
            error_message=str(translated),
        )
        raise translated from exc

    meta = _strip_user_id(meta)
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="get_metadata",
        drive_file_id=file_id,
        drive_file_name=meta.get("name"),
    )
    return meta


async def get_folder_path(
    user_id: int, db: AsyncSession, folder_id: str
) -> list[dict[str, str]]:
    """Chaîne ``[racine, ..., dossier]`` pour les breadcrumbs UI.

    Remonte les ``parents[0]`` jusqu'à ne plus en avoir. Limite implicite
    à 25 niveaux pour ne pas boucler sur un Drive pathologique.
    """
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    segments: list[dict[str, str]] = []
    current_id: Optional[str] = folder_id
    visited: set[str] = set()
    try:
        for _ in range(25):
            if not current_id or current_id in visited:
                break
            visited.add(current_id)
            meta = await asyncio.to_thread(
                lambda cid=current_id: service.files().get(
                    fileId=cid,
                    fields="id, name, parents",
                    supportsAllDrives=True,
                ).execute()
            )
            segments.append({"id": meta["id"], "name": meta.get("name", "")})
            parents = meta.get("parents") or []
            current_id = parents[0] if parents else None
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=folder_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="get_folder_path",
            drive_file_id=folder_id,
            success=False,
            error_message=str(translated),
        )
        raise translated from exc

    segments.reverse()
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="get_folder_path",
        drive_file_id=folder_id,
        details={"depth": len(segments)},
    )
    return segments


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def _guess_mime(file_name: str, fallback: str = "application/octet-stream") -> str:
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed or fallback


async def upload_file(
    user_id: int,
    db: AsyncSession,
    parent_folder_id: str,
    file_name: str,
    file_bytes: bytes,
    mime_type: Optional[str] = None,
) -> dict[str, Any]:
    """Upload multipart d'un fichier. Retourne sa métadonnée."""
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    effective_mime = mime_type or _guess_mime(file_name)
    metadata = {"name": file_name, "parents": [parent_folder_id]}
    media = MediaIoBaseUpload(
        io.BytesIO(file_bytes), mimetype=effective_mime, resumable=False
    )
    try:
        created = await asyncio.to_thread(
            lambda: service.files().create(
                body=metadata,
                media_body=media,
                fields=_FILE_FIELDS,
                supportsAllDrives=True,
            ).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=parent_folder_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="upload",
            drive_file_id=parent_folder_id,
            drive_file_name=file_name,
            success=False,
            error_message=str(translated),
        )
        raise translated from exc

    created = _strip_user_id(created)
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="upload",
        drive_file_id=created.get("id"),
        drive_file_name=created.get("name"),
        details={
            "parent_folder_id": parent_folder_id,
            "size": created.get("size"),
            "mime_type": effective_mime,
        },
    )
    return created


async def upload_file_stream(
    user_id: int,
    db: AsyncSession,
    parent_folder_id: str,
    file_name: str,
    file_stream: io.IOBase,
    mime_type: str,
) -> dict[str, Any]:
    """Variante streaming (resumable). MVP : non optimisé pour > 5 GB."""
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    metadata = {"name": file_name, "parents": [parent_folder_id]}
    media = MediaIoBaseUpload(file_stream, mimetype=mime_type, resumable=True)
    try:
        created = await asyncio.to_thread(
            lambda: service.files().create(
                body=metadata,
                media_body=media,
                fields=_FILE_FIELDS,
                supportsAllDrives=True,
            ).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=parent_folder_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="upload",
            drive_file_id=parent_folder_id,
            drive_file_name=file_name,
            success=False,
            error_message=str(translated),
            details={"streaming": True},
        )
        raise translated from exc

    created = _strip_user_id(created)
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="upload",
        drive_file_id=created.get("id"),
        drive_file_name=created.get("name"),
        details={
            "parent_folder_id": parent_folder_id,
            "size": created.get("size"),
            "mime_type": mime_type,
            "streaming": True,
        },
    )
    return created


# ---------------------------------------------------------------------------
# Download / Export
# ---------------------------------------------------------------------------


# Map Google natif → export MIME suggéré.
_EXPORT_SUGGESTIONS = {
    "application/vnd.google-apps.document": (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "application/vnd.google-apps.presentation": (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
}


async def download_file(
    user_id: int, db: AsyncSession, file_id: str
) -> bytes:
    """Télécharge le contenu binaire brut d'un fichier non natif."""
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    # On lit d'abord la metadata pour vérifier que ce n'est pas un Google natif.
    meta = await get_file_metadata(user_id, db, file_id)
    mime = meta.get("mimeType", "")
    if mime in _GOOGLE_NATIVE_MIMES:
        suggested = _EXPORT_SUGGESTIONS.get(mime, ("application/pdf",))
        raise DriveExportRequired(
            "Ce fichier est un document Google natif et doit être exporté.",
            export_mime_types=list(suggested),
            file_id=file_id,
        )
    buf = io.BytesIO()
    try:
        request = service.files().get_media(
            fileId=file_id, supportsAllDrives=True
        )
        downloader = MediaIoBaseDownload(buf, request)

        def _download_loop() -> None:
            done = False
            while not done:
                _, done = downloader.next_chunk()

        await asyncio.to_thread(_download_loop)
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=file_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="download",
            drive_file_id=file_id,
            drive_file_name=meta.get("name"),
            success=False,
            error_message=str(translated),
        )
        raise translated from exc

    payload = buf.getvalue()
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="download",
        drive_file_id=file_id,
        drive_file_name=meta.get("name"),
        details={"size": len(payload)},
    )
    return payload


async def export_google_doc(
    user_id: int,
    db: AsyncSession,
    file_id: str,
    export_mime_type: str,
) -> bytes:
    """Exporte un Google Doc/Sheet/Slide en format Office ou PDF."""
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    buf = io.BytesIO()
    try:
        request = service.files().export_media(
            fileId=file_id, mimeType=export_mime_type
        )
        downloader = MediaIoBaseDownload(buf, request)

        def _download_loop() -> None:
            done = False
            while not done:
                _, done = downloader.next_chunk()

        await asyncio.to_thread(_download_loop)
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=file_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="export",
            drive_file_id=file_id,
            success=False,
            error_message=str(translated),
            details={"export_mime_type": export_mime_type},
        )
        raise translated from exc

    payload = buf.getvalue()
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="export",
        drive_file_id=file_id,
        details={
            "export_mime_type": export_mime_type,
            "size": len(payload),
        },
    )
    return payload


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


async def rename_file(
    user_id: int, db: AsyncSession, file_id: str, new_name: str
) -> dict[str, Any]:
    """Renomme un fichier ou dossier. Retourne sa nouvelle métadonnée."""
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    try:
        updated = await asyncio.to_thread(
            lambda: service.files().update(
                fileId=file_id,
                body={"name": new_name},
                fields=_FILE_FIELDS,
                supportsAllDrives=True,
            ).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=file_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="rename",
            drive_file_id=file_id,
            drive_file_name=new_name,
            success=False,
            error_message=str(translated),
        )
        raise translated from exc

    updated = _strip_user_id(updated)
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="rename",
        drive_file_id=file_id,
        drive_file_name=new_name,
    )
    return updated


async def move_file(
    user_id: int,
    db: AsyncSession,
    file_id: str,
    new_parent_folder_id: str,
    old_parent_folder_id: Optional[str] = None,
) -> dict[str, Any]:
    """Déplace un fichier.

    Si ``old_parent_folder_id`` est None, on retire automatiquement TOUS
    les parents actuels (cas standard pour un fichier mono-parent).
    """
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    try:
        if old_parent_folder_id is None:
            current = await asyncio.to_thread(
                lambda: service.files().get(
                    fileId=file_id,
                    fields="parents",
                    supportsAllDrives=True,
                ).execute()
            )
            remove_parents = ",".join(current.get("parents", []) or [])
        else:
            remove_parents = old_parent_folder_id

        updated = await asyncio.to_thread(
            lambda: service.files().update(
                fileId=file_id,
                addParents=new_parent_folder_id,
                removeParents=remove_parents or None,
                fields=_FILE_FIELDS,
                supportsAllDrives=True,
            ).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=file_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="move",
            drive_file_id=file_id,
            success=False,
            error_message=str(translated),
            details={"new_parent": new_parent_folder_id},
        )
        raise translated from exc

    updated = _strip_user_id(updated)
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="move",
        drive_file_id=file_id,
        drive_file_name=updated.get("name"),
        details={
            "new_parent": new_parent_folder_id,
            "removed_parents": remove_parents,
        },
    )
    return updated


async def trash_file(
    user_id: int, db: AsyncSession, file_id: str
) -> None:
    """Met le fichier à la corbeille (réversible)."""
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    try:
        await asyncio.to_thread(
            lambda: service.files().update(
                fileId=file_id,
                body={"trashed": True},
                fields="id, trashed",
                supportsAllDrives=True,
            ).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=file_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="trash",
            drive_file_id=file_id,
            success=False,
            error_message=str(translated),
        )
        raise translated from exc

    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="trash",
        drive_file_id=file_id,
    )


async def delete_file_permanent(
    user_id: int, db: AsyncSession, file_id: str
) -> None:
    """Suppression DÉFINITIVE — réservée à un cas explicite UI."""
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    try:
        await asyncio.to_thread(
            lambda: service.files().delete(
                fileId=file_id, supportsAllDrives=True
            ).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=file_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="delete_permanent",
            drive_file_id=file_id,
            success=False,
            error_message=str(translated),
        )
        raise translated from exc

    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="delete_permanent",
        drive_file_id=file_id,
    )


async def restore_from_trash(
    user_id: int, db: AsyncSession, file_id: str
) -> dict[str, Any]:
    """Restaure un fichier depuis la corbeille."""
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    try:
        restored = await asyncio.to_thread(
            lambda: service.files().update(
                fileId=file_id,
                body={"trashed": False},
                fields=_FILE_FIELDS,
                supportsAllDrives=True,
            ).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=file_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="restore",
            drive_file_id=file_id,
            success=False,
            error_message=str(translated),
        )
        raise translated from exc

    restored = _strip_user_id(restored)
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="restore",
        drive_file_id=file_id,
        drive_file_name=restored.get("name"),
    )
    return restored


# ---------------------------------------------------------------------------
# Dossiers
# ---------------------------------------------------------------------------


async def create_folder(
    user_id: int,
    db: AsyncSession,
    parent_folder_id: str,
    folder_name: str,
) -> dict[str, Any]:
    """Crée un nouveau dossier dans ``parent_folder_id``."""
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    body = {
        "name": folder_name,
        "mimeType": FOLDER_MIME,
        "parents": [parent_folder_id],
    }
    try:
        created = await asyncio.to_thread(
            lambda: service.files().create(
                body=body,
                fields=_FILE_FIELDS,
                supportsAllDrives=True,
            ).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=parent_folder_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="create_folder",
            drive_file_id=parent_folder_id,
            drive_file_name=folder_name,
            success=False,
            error_message=str(translated),
        )
        raise translated from exc

    created = _strip_user_id(created)
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="create_folder",
        drive_file_id=created.get("id"),
        drive_file_name=created.get("name"),
        details={"parent_folder_id": parent_folder_id},
    )
    return created


async def _list_all_children(
    service: Resource, folder_id: str
) -> list[dict[str, Any]]:
    """Itère toutes les pages pour récupérer l'ensemble des enfants directs."""
    children: list[dict[str, Any]] = []
    page_token: Optional[str] = None
    query = f"'{folder_id}' in parents and trashed = false"
    while True:
        page = await asyncio.to_thread(
            lambda token=page_token: service.files().list(
                q=query,
                pageSize=1000,
                pageToken=token,
                fields="nextPageToken, files(id, name, mimeType)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
        )
        children.extend(page.get("files", []))
        page_token = page.get("nextPageToken")
        if not page_token:
            break
    return children


async def copy_folder_recursive(
    user_id: int,
    db: AsyncSession,
    source_folder_id: str,
    parent_folder_id: str,
    new_name: Optional[str] = None,
    _depth: int = 0,
    _service: Optional[Resource] = None,
    _root_log: bool = True,
) -> dict[str, Any]:
    """Copie récursive d'un dossier Drive.

    Drive API ne supporte PAS la copie de dossier nativement → on
    crée un dossier vide, on liste le source, et on copie chaque fichier
    (récursion sur les sous-dossiers).

    Protection : profondeur max ``_MAX_COPY_DEPTH`` pour éviter une
    boucle infinie sur un cycle pathologique.
    """
    if _depth > _MAX_COPY_DEPTH:
        raise DriveAPIError(
            f"Profondeur max ({_MAX_COPY_DEPTH}) dépassée lors de la copie."
        )
    service = _service or await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db) if _root_log else None

    # 1. Lire le nom source si new_name non fourni.
    if new_name is None:
        try:
            src_meta = await asyncio.to_thread(
                lambda: service.files().get(
                    fileId=source_folder_id,
                    fields="name",
                    supportsAllDrives=True,
                ).execute()
            )
            new_name = src_meta.get("name", "Copy of folder")
        except HttpError as exc:
            translated = _translate_http_error(exc, file_id=source_folder_id)
            if _root_log:
                await _audit(
                    db,
                    user_id=user_id,
                    google_email=google_email,
                    action="copy_folder_recursive",
                    drive_file_id=source_folder_id,
                    success=False,
                    error_message=str(translated),
                )
            raise translated from exc

    # 2. Créer le dossier cible (NB : create_folder écrit son propre audit
    #    log — c'est OK, on assume la verbosité pour un copy recursive).
    new_folder = await create_folder(
        user_id, db, parent_folder_id, new_name
    )

    # 3. Lister les enfants source et les copier.
    try:
        children = await _list_all_children(service, source_folder_id)
        for child in children:
            child_id = child["id"]
            child_name = child.get("name", "untitled")
            child_mime = child.get("mimeType", "")
            if child_mime == FOLDER_MIME:
                await copy_folder_recursive(
                    user_id,
                    db,
                    child_id,
                    new_folder["id"],
                    new_name=child_name,
                    _depth=_depth + 1,
                    _service=service,
                    _root_log=False,
                )
            else:
                await asyncio.to_thread(
                    lambda cid=child_id, cname=child_name: service.files().copy(
                        fileId=cid,
                        body={"name": cname, "parents": [new_folder["id"]]},
                        fields="id, name",
                        supportsAllDrives=True,
                    ).execute()
                )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=source_folder_id)
        if _root_log:
            await _audit(
                db,
                user_id=user_id,
                google_email=google_email,
                action="copy_folder_recursive",
                drive_file_id=source_folder_id,
                success=False,
                error_message=str(translated),
                details={"target_parent": parent_folder_id},
            )
        raise translated from exc

    if _root_log:
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="copy_folder_recursive",
            drive_file_id=new_folder.get("id"),
            drive_file_name=new_folder.get("name"),
            details={
                "source_folder_id": source_folder_id,
                "target_parent": parent_folder_id,
            },
        )
    return new_folder


# ---------------------------------------------------------------------------
# Recherche
# ---------------------------------------------------------------------------


def _escape_q(value: str) -> str:
    """Échappe quotes et backslashes pour la query Drive ``q=``."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


async def search_files(
    user_id: int,
    db: AsyncSession,
    query: str,
    parent_folder_id: Optional[str] = None,
    *,
    page_size: int = 50,
) -> dict[str, Any]:
    """Cherche par nom ou contenu.

    Si ``parent_folder_id`` est fourni, restreint aux DESCENDANTS directs
    de ce dossier (Drive ne supporte pas la recherche récursive d'un
    seul appel — c'est une limite connue de l'API v3 ; on documente).
    """
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    escaped = _escape_q(query)
    q_parts = [
        f"(name contains '{escaped}' or fullText contains '{escaped}')",
        "trashed = false",
    ]
    if parent_folder_id:
        q_parts.append(f"'{parent_folder_id}' in parents")
    q = " and ".join(q_parts)
    try:
        result = await asyncio.to_thread(
            lambda: service.files().list(
                q=q,
                pageSize=page_size,
                fields=_LIST_FIELDS,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="search",
            success=False,
            error_message=str(translated),
            details={"query": query, "parent": parent_folder_id},
        )
        raise translated from exc

    files = [_strip_user_id(f) for f in result.get("files", [])]
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="search",
        details={
            "query": query,
            "parent": parent_folder_id,
            "count": len(files),
        },
    )
    return {"files": files, "next_page_token": result.get("nextPageToken")}


# ---------------------------------------------------------------------------
# Partage
# ---------------------------------------------------------------------------


_VALID_ROLES = {"reader", "commenter", "writer"}


async def share_file(
    user_id: int,
    db: AsyncSession,
    file_id: str,
    email: str,
    *,
    role: str = "reader",
    send_notification: bool = True,
    message: str = "",
) -> dict[str, Any]:
    """Partage le fichier avec ``email`` au rôle demandé."""
    if role not in _VALID_ROLES:
        raise DriveAPIError(
            f"Rôle invalide : {role}. Attendu : reader, commenter, writer."
        )
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    body = {
        "type": "user",
        "role": role,
        "emailAddress": email,
    }
    try:
        kwargs: dict[str, Any] = {
            "fileId": file_id,
            "body": body,
            "sendNotificationEmail": send_notification,
            "fields": "id, emailAddress, role, displayName, type",
            "supportsAllDrives": True,
        }
        if send_notification and message:
            kwargs["emailMessage"] = message
        permission = await asyncio.to_thread(
            lambda: service.permissions().create(**kwargs).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=file_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="share",
            drive_file_id=file_id,
            success=False,
            error_message=str(translated),
            details={"email": email, "role": role},
        )
        raise translated from exc

    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="share",
        drive_file_id=file_id,
        details={
            "email": email,
            "role": role,
            "permission_id": permission.get("id"),
        },
    )
    return permission


async def list_permissions(
    user_id: int, db: AsyncSession, file_id: str
) -> list[dict[str, Any]]:
    """Liste les permissions du fichier."""
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    try:
        result = await asyncio.to_thread(
            lambda: service.permissions().list(
                fileId=file_id,
                fields="permissions(id, emailAddress, role, displayName, type)",
                supportsAllDrives=True,
            ).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=file_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="list_permissions",
            drive_file_id=file_id,
            success=False,
            error_message=str(translated),
        )
        raise translated from exc

    perms = result.get("permissions", [])
    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="list_permissions",
        drive_file_id=file_id,
        details={"count": len(perms)},
    )
    return perms


async def revoke_permission(
    user_id: int,
    db: AsyncSession,
    file_id: str,
    permission_id: str,
) -> None:
    """Révoque une permission par son id."""
    service = await get_drive_service(user_id, db)
    google_email = await _google_email_for(user_id, db)
    try:
        await asyncio.to_thread(
            lambda: service.permissions().delete(
                fileId=file_id,
                permissionId=permission_id,
                supportsAllDrives=True,
            ).execute()
        )
    except HttpError as exc:
        translated = _translate_http_error(exc, file_id=file_id)
        await _audit(
            db,
            user_id=user_id,
            google_email=google_email,
            action="revoke_permission",
            drive_file_id=file_id,
            success=False,
            error_message=str(translated),
            details={"permission_id": permission_id},
        )
        raise translated from exc

    await _audit(
        db,
        user_id=user_id,
        google_email=google_email,
        action="revoke_permission",
        drive_file_id=file_id,
        details={"permission_id": permission_id},
    )


__all__ = [
    "FOLDER_MIME",
    "copy_folder_recursive",
    "create_folder",
    "delete_file_permanent",
    "download_file",
    "export_google_doc",
    "get_drive_service",
    "get_file_metadata",
    "get_folder_path",
    "list_folder_contents",
    "list_permissions",
    "move_file",
    "rename_file",
    "restore_from_trash",
    "revoke_permission",
    "search_files",
    "share_file",
    "trash_file",
    "upload_file",
    "upload_file_stream",
]
