"""ApiKey — clé d'API personnelle pour l'accès programmatique (lecture seule).

Permet aux assistants externes de Phil (agents Claude) de lire l'activité
du compte de l'utilisateur via une clé porteuse, sans exposer son mot de
passe ni son JWT. La clé n'est JAMAIS stockée en clair : on ne garde que
son hash SHA-256 (`key_hash`) et un préfixe lisible (`key_prefix`, les ~12
premiers caractères) pour que l'utilisateur reconnaisse la clé dans la liste
sans pouvoir la rejouer.

Format de la clé en clair : ``krts_<43 caractères urlsafe>``. Elle est
retournée UNE SEULE FOIS à la création (POST /api/v1/api-keys) et jamais
re-affichable ensuite.

Portée volontairement restreinte : ces clés n'ouvrent QUE les endpoints
d'activité en lecture seule (/api/v1/activity/*). Elles ne sont acceptées
sur aucun endpoint de mutation.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Propriétaire de la clé. CASCADE : si l'utilisateur est supprimé,
    # ses clés disparaissent avec lui.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Hash SHA-256 (hexdigest, 64 caractères) de la clé en clair. On
    # cherche par ce hash à l'authentification. UNIQUE pour éviter toute
    # collision et garantir un lookup déterministe.
    key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )

    # Préfixe lisible de la clé (ex. « krts_a1b2c3d4 »). Sert à
    # reconnaître la clé dans la liste sans jamais révéler le secret.
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)

    # Libellé libre choisi par l'utilisateur (« Agent Claude perso »).
    label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    # Révocation : on garde la ligne (traçabilité) mais is_active=False
    # bloque toute authentification.
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Mis à jour à chaque authentification réussie — traçabilité du
    # dernier usage de la clé. NULL tant que la clé n'a jamais servi.
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Expiration optionnelle. NULL = pas d'expiration.
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<ApiKey(id={self.id}, user_id={self.user_id}, "
            f"prefix='{self.key_prefix}', active={self.is_active})>"
        )
