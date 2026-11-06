"""Révocation complète des accès d'un compte (2026-11-06).

Phil, après avoir désactivé le compte d'un employé renvoyé : « peux-tu me
confirmer qu'il n'a plus accès à rien du tout ? ». Désactiver le compte
(``User.is_active = False``) bloque déjà toutes les requêtes (JWT et clés
d'API : ``get_current_user`` et ``api_key_deps`` refusent un compte inactif),
mais il restait des traces qui pouvaient encore JOINDRE ou SERVIR le compte :

- les abonnements push de ses appareils (une notification ciblée — tâche
  assignée, rappel de punch — pouvait encore arriver sur son téléphone) ;
- ses clés d'API personnelles (inutilisables, mais on les désactive) ;
- son jeton Google Drive lié au compte ;
- ses accès au coffre des abonnements.

``revoquer_acces`` les retire. Idempotent : appelé à la désactivation et
disponible à part (``POST /users/{id}/revoke-access``) pour les comptes
désactivés avant ce correctif.
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.models.drive_user_token import DriveUserToken
from app.models.push_subscription import PushSubscription
from app.models.subscription_vault_access import SubscriptionVaultAccess
from app.models.user import User


def abonnements_actifs_seulement(stmt):
    """Restreint une requête sur ``PushSubscription`` aux comptes ACTIFS : un
    compte désactivé ne doit plus recevoir de notification push, même si un
    appareil est resté abonné."""
    return stmt.where(
        PushSubscription.user_id.in_(select(User.id).where(User.is_active.is_(True)))
    )


async def revoquer_acces(db: AsyncSession, user_id: int) -> Dict[str, Any]:
    """Retire tout ce qui pourrait encore joindre ou servir le compte ``user_id``."""
    push = await db.execute(delete(PushSubscription).where(PushSubscription.user_id == user_id))
    cles = await db.execute(
        update(ApiKey)
        .where(ApiKey.user_id == user_id, ApiKey.is_active.is_(True))
        .values(is_active=False)
    )
    drive = await db.execute(delete(DriveUserToken).where(DriveUserToken.user_id == user_id))
    # L'accès au coffre est une ligne d'octroi sans drapeau : on la retire.
    coffre = await db.execute(delete(SubscriptionVaultAccess).where(SubscriptionVaultAccess.user_id == user_id))
    await db.flush()
    return {
        "push_supprimes": int(push.rowcount or 0),
        "cles_api_desactivees": int(cles.rowcount or 0),
        "jetons_drive_supprimes": int(drive.rowcount or 0),
        "acces_coffre_retires": int(coffre.rowcount or 0),
    }


__all__ = ["revoquer_acces", "abonnements_actifs_seulement"]
