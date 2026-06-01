"""DriveUserToken — token OAuth Google Drive d'un utilisateur Kratos.

Stocke access_token + refresh_token chiffrés (Fernet) pour permettre au
backend d'agir au nom de l'utilisateur sur son Drive sans lui redemander
ses identifiants Google à chaque session.

Un utilisateur n'a qu'un seul token Drive actif : la contrainte d'unicité
sur ``user_id`` garantit le upsert clean lors d'un reconnect.

Voir ``app.services.drive_oauth`` pour l'encryption/decryption et le flow
OAuth complet (Phase 1 de l'intégration Drive).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DriveUserToken(Base):
    __tablename__ = "drive_user_tokens"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_drive_user_tokens_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Email Google effectivement associé au token (peut différer du
    # courriel Kratos — on l'affiche dans l'UI pour confirmer le bon compte).
    google_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    # Tokens chiffrés via Fernet (clé : DRIVE_TOKEN_ENCRYPTION_KEY).
    # LargeBinary pour ne jamais exposer le contenu en clair dans les logs SQL.
    access_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    granted_scopes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
