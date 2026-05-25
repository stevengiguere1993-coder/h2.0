"""Tache d'un projet de developpement - pole Developpement logiciel.

Tache assignable a un dev, optionnellement rattachee a une phase
(DevlogProjectPhase). Si phase_id est NULL, la tache est rattachee
directement au projet (hors planification chronologique).
"""

from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


TASK_STATUSES = ("a_faire", "en_cours", "termine")
TASK_PRIORITIES = ("basse", "moyenne", "haute", "urgente")


class DevlogProjectTask(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_project_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("devlog_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optionnel : rattachement a une phase. NULL = tache flottante.
    phase_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_project_phases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Dev assigne (peut etre NULL le temps de l'assignation).
    assignee_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="a_faire",
        server_default="a_faire",
        index=True,
    )
    priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="moyenne",
        server_default="moyenne",
        index=True,
    )
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<DevlogProjectTask(id={self.id}, "
            f"project_id={self.project_id}, title='{self.title}')>"
        )
