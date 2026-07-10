"""Exceptions d'accès PAR UTILISATEUR (refonte permissions 2026-07).

La règle générale « qui a accès à quoi » est un seuil de rôle par clé
(pages : table ``role_permissions`` avec clé ``page:<page_key>`` ;
actions : clé = id de capacité) + l'accès au volet du pôle. Cette table
permet des EXCEPTIONS individuelles décidées par l'owner :

  - ``allow=True``  → accès ACCORDÉ à cet utilisateur même si son rôle
                      est sous le seuil (et même sans le volet du pôle
                      pour une page — c'est le but d'une exception).
  - ``allow=False`` → accès RETIRÉ à cet utilisateur même si son rôle
                      suffit. (Un owner n'est jamais bloqué.)

``key`` reprend la convention plate du dict ``access`` de /auth/me :
``page:<page_key>``, ``volet:<volet>`` ou ``<capability_id>``.
Nouvelle table → créée par ``create_all``. Une ligne par (user, key).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserAccessOverride(Base):
    __tablename__ = "user_access_overrides"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_access_override"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    allow: Mapped[bool] = mapped_column(Boolean, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<UserAccessOverride(user_id={self.user_id}, "
            f"key='{self.key}', allow={self.allow})>"
        )
