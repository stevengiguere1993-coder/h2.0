"""Corrections / améliorations à faire sur un projet (Flux A).

Liste de points relevés sur un projet (avant ou après livraison) : chacun a
un titre, des détails, et un statut « à faire » (défaut) ou « complété ».
"""

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class ProjectCorrection(Base, TimestampUpdateMixin):
    __tablename__ = "project_corrections"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # "a_faire" (défaut) ou "complete".
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="a_faire", index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
