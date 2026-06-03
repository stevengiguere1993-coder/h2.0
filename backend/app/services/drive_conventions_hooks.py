"""Hooks d'application automatique des Drive Conventions — Phase 5.

Phase 4 a livré le moteur d'application manuelle (bouton « Tester » sur
chaque convention de la page /parametres/drive). Phase 5 branche ces
conventions sur les événements métier de Kratos : à la création d'une
entité supportée (Deal Pipeline, projet Dev logiciel, client Dev
logiciel, lead prospection, projet construction), si une convention
active avec ``trigger_event='created'`` existe pour ce type, le moteur
Phase 4 est invoqué automatiquement en arrière-plan.

Contrat « best-effort » :

- AUCUNE exception non gérée ne doit remonter à l'endpoint appelant.
  Si Drive est down, si le user n'a pas connecté son compte Google, si
  la convention est mal configurée — l'entité Kratos doit être créée
  normalement. Le hook se contente de logger un warning + un audit log
  ``drive_convention.auto_failed`` et retourne ``None``.
- Aucun ``await db.commit()`` n'est fait dans le hook. La session
  injectée par FastAPI (``get_db``) commit en fin de request, ce qui
  persiste l'``DriveEntityLink`` et les ``DriveAuditLog`` ajoutés ici
  en un seul coup.
- Idempotence : si un lien Drive existe déjà pour ``(entity_type,
  entity_id)``, le hook return ``None`` silencieusement (aucun
  doublon ne sera créé).

Limites Phase 5 connues :

- Pas d'asynchronisme « vrai » — l'appel Drive bloque la requête
  (création de l'entité) pendant 3 à 8 secondes selon la latence Drive
  (création du dossier + sous-dossiers). Acceptable pour MVP, Phase 6+
  pourra le déplacer dans une task queue.
- Pas de retry. Une panne réseau ponctuelle = perte d'auto-application
  (Phil pourra cliquer sur Play manuellement depuis /parametres/drive).
- Pas de hook pour la suppression/archive d'entités.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_audit_log import DriveAuditLog
from app.models.drive_convention import DriveConvention
from app.models.drive_entity_link import DriveEntityLink
from app.services import drive_api, drive_conventions_engine, drive_oauth

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------


async def _audit(
    db: AsyncSession,
    *,
    user_id: Optional[int],
    action: str,
    entity_type: str,
    entity_id: int,
    details: Optional[dict] = None,
    success: bool = True,
    error_message: Optional[str] = None,
) -> None:
    """Journalise une décision du hook dans ``drive_audit_logs``.

    Best-effort : si l'insertion elle-même échoue (ex. table absente au
    tout premier boot), on logge mais on n'interrompt rien.
    """
    try:
        entry = DriveAuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            success=success,
            error_message=error_message,
        )
        db.add(entry)
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "drive_conventions_hooks: audit log echoue pour %s/%s (%s) : %s",
            entity_type,
            entity_id,
            action,
            exc,
        )


async def _has_drive_connection(db: AsyncSession, user_id: int) -> bool:
    """Vérifie si le user a une connexion Drive valide (token actif)."""
    try:
        token = await drive_oauth.get_valid_access_token(db, user_id=user_id)
        return bool(token)
    except Exception:  # noqa: BLE001
        return False


async def _existing_link_for(
    entity_type: str, entity_id: int, db: AsyncSession
) -> Optional[DriveEntityLink]:
    stmt = select(DriveEntityLink).where(
        DriveEntityLink.entity_type == entity_type,
        DriveEntityLink.entity_id == entity_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _find_active_convention(
    db: AsyncSession,
    entity_type: str,
    trigger_event: str,
) -> Optional[DriveConvention]:
    """Charge la convention active de plus haute priorité pour ce
    couple ``(entity_type, trigger_event)``.

    En cas d'égalité de ``priority``, on tranche sur ``id`` croissant
    (la plus ancienne gagne — comportement déterministe).
    """
    stmt = (
        select(DriveConvention)
        .where(
            DriveConvention.entity_type == entity_type,
            DriveConvention.trigger_event == trigger_event,
            DriveConvention.active.is_(True),
        )
        .order_by(
            DriveConvention.priority.desc(),
            DriveConvention.id.asc(),
        )
    )
    result = await db.execute(stmt)
    return result.scalars().first()


# ---------------------------------------------------------------------------
# Hook principal — création d'entité
# ---------------------------------------------------------------------------


async def on_entity_created(
    entity_type: str,
    entity_id: int,
    user_id: int,
    db: AsyncSession,
) -> Optional[DriveEntityLink]:
    """Hook à appeler après la création d'une entité Kratos supportée.

    Cherche une convention active avec ``trigger_event='created'`` pour
    ``entity_type``. Si trouvée, applique le moteur Phase 4 pour créer
    le dossier Drive + sous-dossiers et persister le ``DriveEntityLink``.

    Retourne le ``DriveEntityLink`` créé en cas de succès, ``None``
    dans tous les autres cas (aucune convention, déjà lié, Drive
    non connecté, erreur Drive). N'JAMAIS d'exception non gérée.

    Cet appel doit être placé APRÈS le ``await db.flush()`` ou
    ``await db.commit()`` qui donne un ``id`` à l'entité. Si l'endpoint
    appelant rollback ensuite, le ``DriveEntityLink`` sera lui aussi
    rollback côté DB ; en revanche le dossier Drive (créé via API
    Google) restera. C'est un compromis assumé Phase 5 : on accepte ce
    léger "leak" plutôt que de retarder la création Drive après le
    commit (et de perdre la possibilité de logger l'audit dans la même
    transaction).
    """
    try:
        convention = await _find_active_convention(
            db, entity_type=entity_type, trigger_event="created"
        )
        if convention is None:
            # Aucune convention active = comportement attendu, pas de log
            # bruyant. Phil n'a peut-être pas encore activé la convention
            # par défaut sur /parametres/drive — c'est OK.
            return None

        # Idempotence : si l'entité a déjà un lien (ex. réessai côté
        # frontend, double POST), on ne re-crée pas un dossier.
        existing = await _existing_link_for(entity_type, entity_id, db)
        if existing is not None:
            log.info(
                "drive_conventions_hooks: %s#%s deja lie au dossier %s, "
                "hook ignore.",
                entity_type,
                entity_id,
                existing.drive_folder_id,
            )
            return None

        # Vérifie la connexion Drive du user — sans token Google valide,
        # l'appel API échouera de toute façon, autant logger un message
        # clair plutôt qu'une 401 opaque.
        if not await _has_drive_connection(db, user_id):
            log.warning(
                "drive_conventions_hooks: user #%s n'a pas de connexion "
                "Drive, hook 'created' ignore pour %s#%s (convention #%s).",
                user_id,
                entity_type,
                entity_id,
                convention.id,
            )
            await _audit(
                db,
                user_id=user_id,
                action="drive_convention.auto_skipped",
                entity_type=entity_type,
                entity_id=entity_id,
                details={
                    "convention_id": convention.id,
                    "reason": "no_drive_connection",
                },
                success=False,
                error_message=(
                    "Utilisateur sans connexion Drive — convention "
                    "ignorée."
                ),
            )
            return None

        # Vérifie la configuration minimale de la convention.
        if not convention.parent_folder_drive_id:
            log.warning(
                "drive_conventions_hooks: convention #%s sans "
                "parent_folder_drive_id, hook ignore pour %s#%s.",
                convention.id,
                entity_type,
                entity_id,
            )
            await _audit(
                db,
                user_id=user_id,
                action="drive_convention.auto_skipped",
                entity_type=entity_type,
                entity_id=entity_id,
                details={
                    "convention_id": convention.id,
                    "reason": "missing_parent_folder",
                },
                success=False,
                error_message=(
                    "Convention sans parent_folder_drive_id — "
                    "configure-la d'abord sur /parametres/drive."
                ),
            )
            return None

        if not convention.folder_name_template:
            log.warning(
                "drive_conventions_hooks: convention #%s sans "
                "folder_name_template, hook ignore pour %s#%s.",
                convention.id,
                entity_type,
                entity_id,
            )
            await _audit(
                db,
                user_id=user_id,
                action="drive_convention.auto_skipped",
                entity_type=entity_type,
                entity_id=entity_id,
                details={
                    "convention_id": convention.id,
                    "reason": "missing_folder_name_template",
                },
                success=False,
                error_message=(
                    "Convention sans folder_name_template — "
                    "configure-la d'abord sur /parametres/drive."
                ),
            )
            return None

        # Tout est OK — délègue au moteur Phase 4.
        link = await drive_conventions_engine.apply_convention_to_entity(
            convention_id=convention.id,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            db=db,
        )
        await _audit(
            db,
            user_id=user_id,
            action="drive_convention.auto_applied",
            entity_type=entity_type,
            entity_id=entity_id,
            details={
                "convention_id": convention.id,
                "convention_name": convention.name,
                "drive_folder_id": link.drive_folder_id,
                "drive_folder_name": link.drive_folder_name,
            },
        )
        log.info(
            "drive_conventions_hooks: convention #%s auto-appliquee sur "
            "%s#%s -> dossier %s (%s).",
            convention.id,
            entity_type,
            entity_id,
            link.drive_folder_id,
            link.drive_folder_name,
        )
        return link
    except Exception as exc:  # noqa: BLE001
        # Catch large : on n'a AUCUN droit de bloquer la création
        # d'entité Kratos avec une erreur Drive (réseau, quota, etc.).
        log.exception(
            "drive_conventions_hooks: echec auto-application convention "
            "pour %s#%s (user #%s) : %s",
            entity_type,
            entity_id,
            user_id,
            exc,
        )
        await _audit(
            db,
            user_id=user_id,
            action="drive_convention.auto_failed",
            entity_type=entity_type,
            entity_id=entity_id,
            details={"error_class": type(exc).__name__},
            success=False,
            error_message=str(exc)[:1000],
        )
        return None


# ---------------------------------------------------------------------------
# Hook secondaire — changement de statut
# ---------------------------------------------------------------------------


async def on_entity_status_changed(
    entity_type: str,
    entity_id: int,
    old_status: str,
    new_status: str,
    user_id: int,
    db: AsyncSession,
) -> bool:
    """Hook à appeler quand le statut d'une entité change.

    Cherche une convention active avec
    ``trigger_event='status_changed'`` pour ``entity_type``. Si un
    mapping ``status_to_parent_map[new_status]`` est configuré, déplace
    le dossier Drive lié vers le nouveau parent.

    Best-effort identique à :func:`on_entity_created` — jamais
    d'exception non gérée, retourne juste ``True`` si le déplacement a
    réussi, ``False`` sinon.

    Si l'entité n'a pas encore de lien Drive (jamais auto-créé via la
    convention ``created``, et jamais lié manuellement), on ne fait
    rien — créer rétroactivement un dossier à un changement de statut
    serait surprenant pour Phil.
    """
    if not new_status or new_status == old_status:
        # Pas un vrai changement — court-circuit silencieux.
        return False
    try:
        convention = await _find_active_convention(
            db, entity_type=entity_type, trigger_event="status_changed"
        )
        if convention is None:
            return False

        status_map = convention.status_to_parent_map or {}
        if not isinstance(status_map, dict):
            return False
        new_parent_id = status_map.get(new_status)
        if not new_parent_id:
            # Aucun mapping pour ce statut — comportement attendu, pas de
            # log bruyant.
            return False

        # Récupère le lien existant — on ne crée pas rétroactivement.
        link = await _existing_link_for(entity_type, entity_id, db)
        if link is None:
            log.info(
                "drive_conventions_hooks: %s#%s sans lien Drive, hook "
                "status_changed ignore (convention #%s, %s -> %s).",
                entity_type,
                entity_id,
                convention.id,
                old_status,
                new_status,
            )
            return False

        if not await _has_drive_connection(db, user_id):
            log.warning(
                "drive_conventions_hooks: user #%s sans connexion Drive, "
                "deplacement %s#%s ignore.",
                user_id,
                entity_type,
                entity_id,
            )
            await _audit(
                db,
                user_id=user_id,
                action="drive_convention.auto_move_skipped",
                entity_type=entity_type,
                entity_id=entity_id,
                details={
                    "convention_id": convention.id,
                    "new_status": new_status,
                    "reason": "no_drive_connection",
                },
                success=False,
            )
            return False

        await drive_api.move_file(
            user_id=user_id,
            db=db,
            file_id=link.drive_folder_id,
            new_parent_folder_id=new_parent_id,
        )
        await _audit(
            db,
            user_id=user_id,
            action="drive_convention.auto_moved",
            entity_type=entity_type,
            entity_id=entity_id,
            details={
                "convention_id": convention.id,
                "old_status": old_status,
                "new_status": new_status,
                "drive_folder_id": link.drive_folder_id,
                "new_parent_folder_id": new_parent_id,
            },
        )
        log.info(
            "drive_conventions_hooks: %s#%s deplace vers %s suite au "
            "changement %s -> %s (convention #%s).",
            entity_type,
            entity_id,
            new_parent_id,
            old_status,
            new_status,
            convention.id,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.exception(
            "drive_conventions_hooks: echec hook status_changed pour "
            "%s#%s (%s -> %s) : %s",
            entity_type,
            entity_id,
            old_status,
            new_status,
            exc,
        )
        await _audit(
            db,
            user_id=user_id,
            action="drive_convention.auto_move_failed",
            entity_type=entity_type,
            entity_id=entity_id,
            details={
                "old_status": old_status,
                "new_status": new_status,
                "error_class": type(exc).__name__,
            },
            success=False,
            error_message=str(exc)[:1000],
        )
        return False


__all__ = [
    "on_entity_created",
    "on_entity_status_changed",
]
