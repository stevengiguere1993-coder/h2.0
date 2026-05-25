"""DevlogProjectPhoto — photo (ou PDF) attachee a un DevlogProject.

Stockage du blob en colonne BYTEA dans la BD (meme pattern que
``ProjectPhoto`` du pole Construction). Pas de service objet externe :
l'app est self-contained sur Render + Postgres et les volumes restent
raisonnables (images compressees < 15 Mo chacune).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base


class DevlogProjectPhoto(Base):
    __tablename__ = "devlog_project_photos"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("devlog_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Blob deferred : les listes ne paient pas le cout transfert reseau.
    image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=False)
    )
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    uploaded_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    uploaded_by_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<DevlogProjectPhoto(id={self.id}, "
            f"project_id={self.project_id}, ct='{self.content_type}')>"
        )
