"""Premier compte OWNER sur une base VIDE (staging).

L'inscription Kratos est réservée aux admins (« register » exige
CurrentAdmin) — sur une base de données neuve (dev.immohorizon.com), il
n'existe AUCUN utilisateur, donc personne pour créer le premier compte.

Ce bootstrap tourne au démarrage : si ``BOOTSTRAP_ADMIN_EMAIL`` et
``BOOTSTRAP_ADMIN_PASSWORD`` sont définis ET que la table users est
VIDE, il crée un compte owner. Dès qu'un utilisateur existe (même un
seul), il ne fait plus JAMAIS rien — poser ces variables sur la prod est
donc sans effet, et les changer après coup ne modifie aucun compte.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select

log = logging.getLogger("bootstrap_admin")


async def ensure_bootstrap_admin() -> None:
    from app.core.config import settings

    email = (getattr(settings, "bootstrap_admin_email", "") or "").strip()
    password = getattr(settings, "bootstrap_admin_password", "") or ""
    if not email or not password:
        return

    from app.core.security import get_password_hash
    from app.db.session import AsyncSessionLocal
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        nb = (await db.execute(select(func.count(User.id)))).scalar() or 0
        if nb > 0:
            return  # des comptes existent — on ne touche à rien
        user = User(
            email=email.lower(),
            hashed_password=get_password_hash(password),
            is_active=True,
            is_admin=True,
            role=UserRole.OWNER.value,
        )
        db.add(user)
        await db.commit()
        log.warning(
            "Base vide : compte OWNER de démarrage créé pour %s "
            "(BOOTSTRAP_ADMIN_EMAIL).", email,
        )
