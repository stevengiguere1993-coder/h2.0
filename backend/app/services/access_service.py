"""Calcul de l'accès COMPLET d'un utilisateur (refonte permissions 2026-07).

``compute_access(db, user)`` renvoie le dict plat consommé par /auth/me
(champ ``access`` de UserRead) et par la vue « par utilisateur » de
Paramètres → Permissions :

    {
      "volet:construction": true,          # accès au pôle
      "page:construction.projets": true,   # visibilité d'une page
      "telephonie.access": false,          # capacité (action)
      ...
    }

Règles de combinaison :
  - volet    : ``User.has_volet`` (owner/admin = tous).
  - page     : volet de la page (sauf "general") ET rôle ≥ seuil configuré
               (table role_permissions clé ``page:<key>``, fallback registre).
  - capacité : rôle ≥ seuil configuré (fallback registre capabilities).
  - overrides individuels (``user_access_overrides``) par-dessus tout :
    allow=True force l'accès (même sans volet — c'est le but d'une
    exception), allow=False le retire. Un OWNER n'est jamais bloqué.
"""
from __future__ import annotations

from sqlalchemy import select

from app.core.access_registry import PAGE_KEY_PREFIX, PAGES, GENERAL
from app.core.capabilities import CAPABILITIES
from app.models.user import VALID_VOLETS, User
from app.models.user_access_override import UserAccessOverride
from app.services.permissions_service import get_min_role


async def compute_access(db, user: User) -> dict[str, bool]:
    out: dict[str, bool] = {}
    volets = set(user.volets)

    # 1) Volets (accès aux pôles).
    for v in VALID_VOLETS:
        out[f"volet:{v}"] = v in volets

    # 2) Pages : volet du pôle + seuil de rôle configurable.
    for page in PAGES:
        key = f"{PAGE_KEY_PREFIX}{page.key}"
        min_role = await get_min_role(key)
        role_ok = user.has_min_role(min_role)
        volet_ok = page.volet == GENERAL or page.volet in volets
        out[key] = role_ok and volet_ok

    # 3) Capacités (actions) — mêmes clés qu'avant (rétrocompat
    #    telephonie.access / devlog.access incluses).
    for cap in CAPABILITIES:
        out[cap.id] = user.has_min_role(await get_min_role(cap.id))

    # 4) Exceptions individuelles (owner jamais bloqué).
    rows = (
        await db.execute(
            select(UserAccessOverride).where(
                UserAccessOverride.user_id == user.id
            )
        )
    ).scalars().all()
    is_owner = user.role == "owner"
    for row in rows:
        if row.allow:
            out[row.key] = True
        elif not is_owner:
            out[row.key] = False

    return out
