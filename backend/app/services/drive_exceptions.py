"""Exceptions custom du wrapper Drive API.

Toutes ces exceptions héritent de :class:`DriveError` et exposent un
message lisible en français côté :attr:`args[0]`, plus l'exception
Google d'origine sur :attr:`original` quand pertinent.

Les endpoints :mod:`app.api.v1.endpoints.drive_files` les attrapent et
les traduisent en HTTPException avec le bon status code.
"""

from __future__ import annotations

from typing import Optional


class DriveError(Exception):
    """Base — toutes les erreurs Drive Kratos en héritent."""

    def __init__(self, message: str, *, original: Optional[BaseException] = None):
        super().__init__(message)
        self.message = message
        self.original = original


class DriveAuthError(DriveError):
    """L'utilisateur n'a pas connecté son Drive, ou token invalide / expiré.

    Mappé en HTTP 401 côté endpoints.
    """


class DriveNotFoundError(DriveError):
    """Fichier ou dossier introuvable (ou inaccessible avec les scopes actuels).

    Mappé en HTTP 404 côté endpoints. Note : avec le scope ``drive.file``,
    Google répond 404 même si le fichier existe mais n'a pas été ouvert
    ou créé par Kratos — l'utilisateur ne peut tout simplement pas le
    voir.
    """


class DrivePermissionError(DriveError):
    """Google a refusé l'opération (permissions insuffisantes).

    Mappé en HTTP 403 côté endpoints.
    """


class DriveExportRequired(DriveError):
    """Fichier Google natif (Docs / Sheets / Slides) — passer par /export.

    Mappé en HTTP 409 côté endpoints, avec ``export_mime_types`` dans le
    payload pour que l'UI propose des formats valides.
    """

    def __init__(
        self,
        message: str,
        *,
        export_mime_types: list[str],
        file_id: Optional[str] = None,
        original: Optional[BaseException] = None,
    ):
        super().__init__(message, original=original)
        self.export_mime_types = export_mime_types
        self.file_id = file_id


class DriveQuotaExceeded(DriveError):
    """Quota Google dépassé (rate limit ou storage).

    Mappé en HTTP 429 côté endpoints.
    """


class DriveAPIError(DriveError):
    """Erreur Drive non catégorisée (5xx Google, network, etc.).

    Mappé en HTTP 502 côté endpoints.
    """


__all__ = [
    "DriveAPIError",
    "DriveAuthError",
    "DriveError",
    "DriveExportRequired",
    "DriveNotFoundError",
    "DrivePermissionError",
    "DriveQuotaExceeded",
]
