"""Dispatcher d'auto-upload de documents Kratos vers Drive — Phase 6.

Dernière brique de l'intégration Drive : quand Kratos génère un document
(PDF d'une fiche d'analyse, NDA signé, soumission, facture, offre PPTX),
le déposer AUTOMATIQUEMENT dans le bon sous-dossier Drive de l'entité
concernée — sans intervention humaine.

Contrat « best-effort » ABSOLU :

- Ce module ne lève JAMAIS d'exception vers l'endpoint appelant. Tous les
  chemins d'échec retournent ``None``. La génération du document et sa
  réponse au client ne doivent jamais être bloquées parce que Drive est
  down, qu'aucune règle n'est active, ou que l'entité n'a pas de dossier
  lié.
- Aucune règle active pour ``(document_type, entity_type)`` → ``None``
  silencieux (Phil n'a peut-être pas encore activé la règle).
- Aucun ``DriveEntityLink`` pour ``(entity_type, entity_id)`` → audit
  ``drive_auto_upload.no_link`` + ``None``.
- Pas de connexion Drive valide pour le ``user_id`` → audit
  ``drive_auto_upload.no_connection`` + ``None``.

Flux nominal :

1. Charger la règle :class:`DriveAutoUpload` active pour
   ``(document_type, entity_type)`` (la plus récente gagne).
2. Charger le :class:`DriveEntityLink` ``(entity_type, entity_id)`` →
   ``drive_folder_id`` racine de l'entité.
3. Résoudre le sous-dossier cible depuis ``subfolder_path_template``
   (création récursive idempotente via :func:`ensure_subfolder_path`).
4. Résoudre le nom de fichier depuis ``file_name_template`` +
   ``template_vars``.
5. Appliquer la stratégie ``overwrite_strategy`` :
   - ``overwrite``  : corbeille le fichier de même nom puis upload.
   - ``version``    : suffixe horodaté ``_AAAAMMJJ-HHMMSS`` (historique).
   - ``keep_both``  : upload tel quel (Drive tolère les doublons de nom).
6. Upload via :func:`drive_api.upload_file`. Audit
   ``drive_auto_upload.uploaded``.

Note sur ``user_id`` : le wrapper :mod:`drive_api` agit pour le compte
d'un utilisateur Kratos connecté à Google Drive. Les endpoints
authentifiés passent ``user.id``. Les endpoints publics (ex. signature
NDA) n'ont pas d'utilisateur — ils passent ``None`` et le dispatcher
résout un « propriétaire Drive » (premier utilisateur avec un token Drive
valide) via :func:`resolve_drive_owner_user_id`.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_audit_log import DriveAuditLog
from app.models.drive_auto_upload import DriveAutoUpload
from app.models.drive_entity_link import DriveEntityLink
from app.models.drive_user_token import DriveUserToken
from app.services import drive_api, drive_oauth

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audit helper (best-effort)
# ---------------------------------------------------------------------------


async def _audit(
    db: AsyncSession,
    *,
    user_id: Optional[int],
    action: str,
    entity_type: str,
    entity_id: int,
    drive_file_id: Optional[str] = None,
    drive_file_name: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    success: bool = True,
    error_message: Optional[str] = None,
) -> None:
    """Journalise une décision du dispatcher dans ``drive_audit_logs``."""
    try:
        entry = DriveAuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            drive_file_id=drive_file_id,
            drive_file_name=drive_file_name,
            details=details,
            success=success,
            error_message=error_message,
        )
        db.add(entry)
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "drive_auto_upload_dispatcher: audit log echoue pour %s/%s (%s): %s",
            entity_type,
            entity_id,
            action,
            exc,
        )


# ---------------------------------------------------------------------------
# Résolution du « propriétaire Drive » (pour les endpoints publics)
# ---------------------------------------------------------------------------


async def resolve_drive_owner_user_id(
    db: AsyncSession, preferred_user_id: Optional[int] = None
) -> Optional[int]:
    """Retourne un ``user_id`` capable d'agir sur Drive.

    - Si ``preferred_user_id`` a un token Drive valide, on le retourne.
    - Sinon, on retourne le premier utilisateur ayant un
      :class:`DriveUserToken` (créé le plus tôt — déterministe).
    - ``None`` si personne n'a connecté Drive.

    Utilisé par les endpoints publics (signature NDA) qui n'ont pas de
    contexte d'authentification mais doivent quand même déposer un
    document dans le Drive « Horizon ».
    """
    try:
        if preferred_user_id is not None:
            token = await drive_oauth.get_valid_access_token(
                db, user_id=preferred_user_id
            )
            if token:
                return preferred_user_id

        row = (
            await db.execute(
                select(DriveUserToken.user_id).order_by(
                    DriveUserToken.id.asc()
                )
            )
        ).first()
        return row[0] if row else None
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "drive_auto_upload_dispatcher: resolution drive owner echouee: %s",
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Résolution des templates
# ---------------------------------------------------------------------------


_NOW_PLACEHOLDERS = {
    "date",  # AAAA-MM-JJ
    "datetime",  # AAAA-MM-JJ_HHMMSS
    "annee",  # AAAA
    "year",  # AAAA (alias EN)
    "mois",  # MM
    "jour",  # JJ
    "timestamp",  # AAAAMMJJ-HHMMSS
}


def _auto_template_vars() -> dict[str, str]:
    now = datetime.now(timezone.utc)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "datetime": now.strftime("%Y-%m-%d_%H%M%S"),
        "annee": now.strftime("%Y"),
        "year": now.strftime("%Y"),
        "mois": now.strftime("%m"),
        "jour": now.strftime("%d"),
        "timestamp": now.strftime("%Y%m%d-%H%M%S"),
    }


_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")
# Caractères interdits/risqués dans un nom de fichier ou dossier Drive.
_UNSAFE_CHARS_RE = re.compile(r'[\\/:*?"<>|]')


def _sanitize_segment(value: str) -> str:
    """Nettoie un segment de chemin / nom de fichier pour Drive."""
    cleaned = _UNSAFE_CHARS_RE.sub(" ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:200]


def resolve_template(
    template: Optional[str], template_vars: Optional[dict[str, Any]]
) -> str:
    """Substitue ``{placeholders}`` dans ``template``.

    Combine les variables auto (date, timestamp, ...) avec celles
    fournies par l'appelant. Un placeholder inconnu est laissé vide
    plutôt que de planter (best-effort).
    """
    if not template:
        return ""
    merged: dict[str, Any] = dict(_auto_template_vars())
    if template_vars:
        for key, val in template_vars.items():
            if val is not None:
                merged[key] = str(val)

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(merged.get(key, ""))

    return _PLACEHOLDER_RE.sub(_replace, template)


# ---------------------------------------------------------------------------
# Sous-dossiers : création/recherche récursive idempotente
# ---------------------------------------------------------------------------


async def _find_child_folder(
    user_id: int,
    db: AsyncSession,
    parent_folder_id: str,
    name: str,
) -> Optional[str]:
    """Retourne l'id d'un sous-dossier nommé ``name`` (ou ``None``)."""
    listing = await drive_api.list_folder_contents(
        user_id, db, parent_folder_id, page_size=1000
    )
    target = name.strip().casefold()
    for f in listing.get("files", []):
        if (
            f.get("mimeType") == drive_api.FOLDER_MIME
            and (f.get("name") or "").strip().casefold() == target
        ):
            return f.get("id")
    return None


async def ensure_subfolder_path(
    user_id: int,
    root_folder_id: str,
    path: Optional[str],
    db: AsyncSession,
) -> str:
    """Garantit l'existence de chaque segment de ``path`` sous la racine.

    ``path`` peut contenir des ``/`` (ex. ``"Dossier investisseur/NDA"``).
    Chaque segment est cherché (insensible à la casse) ; s'il n'existe
    pas, il est créé. Retourne l'id du dossier le plus profond. Si
    ``path`` est vide, retourne ``root_folder_id`` (dépôt à la racine de
    l'entité).
    """
    if not path or not path.strip():
        return root_folder_id

    current = root_folder_id
    segments = [
        _sanitize_segment(seg)
        for seg in path.replace("\\", "/").split("/")
        if seg.strip()
    ]
    for seg in segments:
        if not seg:
            continue
        existing = await _find_child_folder(user_id, db, current, seg)
        if existing:
            current = existing
            continue
        created = await drive_api.create_folder(user_id, db, current, seg)
        current = created["id"]
    return current


# ---------------------------------------------------------------------------
# Stratégie overwrite
# ---------------------------------------------------------------------------


async def _trash_existing_same_name(
    user_id: int,
    db: AsyncSession,
    parent_folder_id: str,
    file_name: str,
) -> int:
    """Corbeille les fichiers (non-dossiers) de même nom. Retourne le compte."""
    listing = await drive_api.list_folder_contents(
        user_id, db, parent_folder_id, page_size=1000
    )
    target = file_name.strip().casefold()
    trashed = 0
    for f in listing.get("files", []):
        if (
            f.get("mimeType") != drive_api.FOLDER_MIME
            and (f.get("name") or "").strip().casefold() == target
        ):
            try:
                await drive_api.trash_file(user_id, db, f["id"])
                trashed += 1
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "drive_auto_upload_dispatcher: corbeille echouee pour "
                    "%s (%s): %s",
                    f.get("id"),
                    file_name,
                    exc,
                )
    return trashed


def _apply_version_suffix(file_name: str) -> str:
    """Insère un suffixe horodaté avant l'extension."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dot = file_name.rfind(".")
    if dot > 0:
        return f"{file_name[:dot]}_{stamp}{file_name[dot:]}"
    return f"{file_name}_{stamp}"


# ---------------------------------------------------------------------------
# Chargements DB
# ---------------------------------------------------------------------------


async def _load_active_rule(
    db: AsyncSession, document_type: str, entity_type: str
) -> Optional[DriveAutoUpload]:
    stmt = (
        select(DriveAutoUpload)
        .where(
            DriveAutoUpload.document_type == document_type,
            DriveAutoUpload.entity_type == entity_type,
            DriveAutoUpload.active.is_(True),
        )
        .order_by(DriveAutoUpload.id.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def _load_entity_link(
    db: AsyncSession, entity_type: str, entity_id: int
) -> Optional[DriveEntityLink]:
    stmt = select(DriveEntityLink).where(
        DriveEntityLink.entity_type == entity_type,
        DriveEntityLink.entity_id == entity_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------


async def dispatch_auto_upload(
    document_type: str,
    entity_type: str,
    entity_id: Optional[int],
    user_id: Optional[int],
    file_bytes: bytes,
    db: AsyncSession,
    template_vars: Optional[dict[str, Any]] = None,
    *,
    mime_type: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Dépose ``file_bytes`` dans le Drive de l'entité selon la règle active.

    Best-effort : retourne la métadonnée Drive du fichier uploadé en cas
    de succès, ``None`` dans TOUS les autres cas (aucune règle, pas de
    lien, Drive down, ...). Ne lève jamais.

    Args:
        document_type: ``"fiche_analyse"``, ``"nda_signed"``,
            ``"soumission_pdf"``, ``"offre_pptx"``, ``"facture_pdf"``.
        entity_type: type d'entité du :class:`DriveEntityLink`
            (``"ProspectionDeal"``, ``"DevlogClient"``, ...).
        entity_id: id de l'entité. ``None`` → no-op silencieux (ex.
            fiche d'analyse non convertie en deal).
        user_id: utilisateur Kratos pour le compte duquel agir sur Drive.
            ``None`` (endpoints publics) → résolution d'un propriétaire.
        file_bytes: contenu binaire du document généré.
        template_vars: variables de substitution (ex. ``{"numero": "F-12",
            "nom_signataire": "Jean"}``).
        mime_type: MIME explicite (sinon déduit du nom de fichier).
    """
    try:
        if entity_id is None:
            # Cas courant : la fiche d'analyse n'a pas (encore) de deal
            # lié. Pas un échec — comportement attendu.
            return None
        if not file_bytes:
            return None

        rule = await _load_active_rule(db, document_type, entity_type)
        if rule is None:
            # Aucune règle active = Phil n'a pas (encore) activé
            # l'auto-classement pour ce type. Silencieux.
            return None

        effective_user_id = await resolve_drive_owner_user_id(db, user_id)
        if effective_user_id is None:
            log.info(
                "drive_auto_upload: aucun user connecte a Drive, upload %s "
                "ignore pour %s#%s.",
                document_type,
                entity_type,
                entity_id,
            )
            await _audit(
                db,
                user_id=user_id,
                action="drive_auto_upload.no_connection",
                entity_type=entity_type,
                entity_id=entity_id,
                details={"document_type": document_type, "rule_id": rule.id},
                success=False,
                error_message="Aucun utilisateur connecté à Drive.",
            )
            return None

        link = await _load_entity_link(db, entity_type, entity_id)
        if link is None:
            log.info(
                "drive_auto_upload: %s#%s sans dossier Drive lie, upload %s "
                "ignore.",
                entity_type,
                entity_id,
                document_type,
            )
            await _audit(
                db,
                user_id=effective_user_id,
                action="drive_auto_upload.no_link",
                entity_type=entity_type,
                entity_id=entity_id,
                details={"document_type": document_type, "rule_id": rule.id},
                success=False,
                error_message=(
                    "Aucun DriveEntityLink — l'entité n'a pas de dossier "
                    "Drive (crée-le ou lie-le d'abord)."
                ),
            )
            return None

        # 3. Sous-dossier cible (créé/trouvé récursivement).
        subfolder_path = resolve_template(
            rule.subfolder_path_template, template_vars
        )
        target_folder_id = await ensure_subfolder_path(
            effective_user_id, link.drive_folder_id, subfolder_path, db
        )

        # 4. Nom du fichier.
        file_name = _sanitize_segment(
            resolve_template(rule.file_name_template, template_vars)
        )
        if not file_name:
            # Fallback raisonnable si le template est vide/mal résolu.
            file_name = f"{document_type}_{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"

        # 5. Stratégie overwrite.
        strategy = (rule.overwrite_strategy or "version").lower()
        if strategy == "overwrite":
            await _trash_existing_same_name(
                effective_user_id, db, target_folder_id, file_name
            )
        elif strategy == "version":
            file_name = _apply_version_suffix(file_name)
        # "keep_both" : pas de pré-traitement, Drive tolère les doublons.

        # 6. Upload.
        created = await drive_api.upload_file(
            effective_user_id,
            db,
            target_folder_id,
            file_name,
            file_bytes,
            mime_type=mime_type,
        )

        await _audit(
            db,
            user_id=effective_user_id,
            action="drive_auto_upload.uploaded",
            entity_type=entity_type,
            entity_id=entity_id,
            drive_file_id=created.get("id"),
            drive_file_name=created.get("name"),
            details={
                "document_type": document_type,
                "rule_id": rule.id,
                "rule_name": rule.name,
                "strategy": strategy,
                "subfolder_path": subfolder_path,
                "target_folder_id": target_folder_id,
                "size_bytes": len(file_bytes),
            },
        )
        log.info(
            "drive_auto_upload: %s depose pour %s#%s -> %s (%s octets, "
            "regle #%s, strategie %s).",
            document_type,
            entity_type,
            entity_id,
            created.get("name"),
            len(file_bytes),
            rule.id,
            strategy,
        )
        return created
    except Exception as exc:  # noqa: BLE001
        # Catch large : on ne bloque JAMAIS la génération du document.
        log.exception(
            "drive_auto_upload: echec non bloquant pour %s (%s#%s): %s",
            document_type,
            entity_type,
            entity_id,
            exc,
        )
        try:
            await _audit(
                db,
                user_id=user_id,
                action="drive_auto_upload.failed",
                entity_type=entity_type,
                entity_id=entity_id if entity_id is not None else 0,
                details={
                    "document_type": document_type,
                    "error_class": type(exc).__name__,
                },
                success=False,
                error_message=str(exc)[:1000],
            )
        except Exception:  # noqa: BLE001
            pass
        return None


__all__ = [
    "dispatch_auto_upload",
    "ensure_subfolder_path",
    "resolve_template",
    "resolve_drive_owner_user_id",
]
