"""ApiKey — clé d'API personnelle pour l'accès programmatique.

Permet aux assistants externes de Phil (agents Claude) de lire l'activité
du compte de l'utilisateur — et, depuis l'ajout des permissions par pôle,
d'effectuer certaines écritures explicitement autorisées (ex. créer une
tâche d'un pôle) — via une clé porteuse, sans exposer son mot de passe ni
son JWT. La clé n'est JAMAIS stockée en clair : on ne garde que son hash
SHA-256 (`key_hash`) et un préfixe lisible (`key_prefix`, les ~12 premiers
caractères) pour que l'utilisateur reconnaisse la clé dans la liste sans
pouvoir la rejouer.

Format de la clé en clair : ``krts_<43 caractères urlsafe>``. Elle est
retournée UNE SEULE FOIS à la création (POST /api/v1/api-keys) et jamais
re-affichable ensuite.

Permissions PAR PÔLE (``scopes``) : liste JSON de chaînes au format
``<pole>:<capability>`` (ex. ``devlog:activity:read``,
``prospection:tasks:create``). Le catalogue des capacités vit dans
``app.services.api_capabilities``. Une clé ne fait QUE ce que ses scopes
autorisent, pôle par pôle. RÉTROCOMPAT : une clé sans ``scopes`` (NULL/[])
ou avec l'ancien ``activity:read`` global est traitée comme « lecture de
TOUS les pôles » — voir ``api_capabilities.key_has_scope``.
"""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
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

    # Permissions par pôle : liste JSON de scopes « <pole>:<capability> ».
    # NULL = pas de scopes explicites → rétrocompat : lecture de TOUS les
    # pôles (jamais d'écriture). La colonne est ajoutée de façon additive
    # au démarrage (init_db) pour ne pas casser les clés existantes.
    scopes_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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

    # ── Helpers scopes ────────────────────────────────────────────────

    @property
    def scopes(self) -> Optional[list[str]]:
        """Liste de scopes décodée, ou None si la clé n'a pas de scopes
        explicites (→ rétrocompat lecture tous pôles). Best-effort : un
        JSON corrompu est traité comme « pas de scopes »."""
        if not self.scopes_json:
            return None
        try:
            data = json.loads(self.scopes_json)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, list):
            return None
        return [s for s in data if isinstance(s, str)]

    @scopes.setter
    def scopes(self, value: Optional[list[str]]) -> None:
        if not value:
            self.scopes_json = None
        else:
            self.scopes_json = json.dumps(list(value))

    def __repr__(self) -> str:
        return (
            f"<ApiKey(id={self.id}, user_id={self.user_id}, "
            f"prefix='{self.key_prefix}', active={self.is_active})>"
        )
