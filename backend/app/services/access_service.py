"""Calcul de l'accès COMPLET d'un utilisateur (permissions v2, 2026-07-24).

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
  - DÉRIVATION FINALE : un volet est accessible dès qu'AU MOINS UNE de
    ses pages l'est — une exception de page suffit donc à ouvrir le pôle
    (tuile du portail, layout ET routeurs API via ``user_has_volet_access``),
    sans donner les autres pages.
"""
from __future__ import annotations

from sqlalchemy import select

from app.core.access_registry import GENERAL, PAGE_KEY_PREFIX, PAGES
from app.core.capabilities import CAPABILITIES
from app.models.user import VALID_VOLETS, User
from app.models.user_access_override import UserAccessOverride
from app.services.permissions_service import get_min_role

#: Clés de pages par volet (ex. developpement_logiciel → devlogiciel.*) —
#: le préfixe de clé ne suit pas toujours le nom du volet, on passe par
#: le registre.
PAGE_KEYS_BY_VOLET: dict[str, tuple[str, ...]] = {
    v: tuple(p.key for p in PAGES if p.volet == v) for v in VALID_VOLETS
}


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

    # 5) Dérivation : le volet suit ses pages — une page accordée (par
    #    rôle OU par exception) ouvre le pôle ; un volet dont AUCUNE page
    #    n'est visible reste fermé même s'il est coché (rien à y voir).
    for v in VALID_VOLETS:
        page_keys = PAGE_KEYS_BY_VOLET.get(v, ())
        if not page_keys:
            continue
        out[f"volet:{v}"] = any(
            out.get(f"{PAGE_KEY_PREFIX}{k}") for k in page_keys
        )

    return out


async def user_has_volet_access(db, user: User, *volets: str) -> bool:
    """Accès au pôle pour les GARDES API (``require_volet``) — mêmes
    règles que ``compute_access`` : volet coché OU au moins une page du
    volet accordée en exception individuelle. Chemin rapide sans requête
    quand le volet est coché (cas normal)."""
    if any(user.has_volet(v) for v in volets):
        return True
    # Exceptions individuelles : volet:<v> ou n'importe quelle page du
    # volet accordée → le pôle (et ses API) s'ouvrent.
    allowed_keys: set[str] = set()
    for v in volets:
        allowed_keys.add(f"volet:{v}")
        for k in PAGE_KEYS_BY_VOLET.get(v, ()):
            allowed_keys.add(f"{PAGE_KEY_PREFIX}{k}")
    if not allowed_keys:
        return False
    rows = (
        await db.execute(
            select(UserAccessOverride.key).where(
                UserAccessOverride.user_id == user.id,
                UserAccessOverride.allow.is_(True),
                UserAccessOverride.key.in_(sorted(allowed_keys)),
            )
        )
    ).all()
    return len(rows) > 0
