"""Saisie d'heures — pôle Développement logiciel.

Suivi du temps passé par les devs sur les projets du pôle.
"""

from datetime import date
from typing import Optional

from sqlalchemy import Date, Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class DevlogTimeEntry(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_time_entries"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Dev qui a saisi les heures.
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<DevlogTimeEntry(id={self.id}, project_id={self.project_id}, hours={self.hours})>"
