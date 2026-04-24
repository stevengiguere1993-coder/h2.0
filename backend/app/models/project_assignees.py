"""Join tables for multi-assignee phases and tasks.

Historically each ProjectPhase and ProjectTask had at most one
assignee (an employe OR a sous-traitant). The construction reality
is that several people frequently work the same phase — démolition
team, two electricians on the same day, etc. We keep the legacy
single-assignee columns for backward compatibility (they're kept in
sync with the « primary » assignee) and expose lists through the API.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProjectPhaseAssignee(Base):
    """N-to-M : une phase peut être assignée à plusieurs personnes
    (employés + sous-traitants mélangés). Contrainte d'unicité par
    (phase, employe) et (phase, sous_traitant) pour éviter les
    doublons, l'autre colonne étant NULL dans chaque ligne."""

    __tablename__ = "project_phase_assignees"
    __table_args__ = (
        UniqueConstraint(
            "phase_id", "employe_id", name="uq_phase_assignee_employe"
        ),
        UniqueConstraint(
            "phase_id",
            "sous_traitant_id",
            name="uq_phase_assignee_sous_traitant",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    phase_id: Mapped[int] = mapped_column(
        ForeignKey("project_phases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employe_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    sous_traitant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sous_traitants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ProjectTaskAssignee(Base):
    """N-to-M : une tâche peut être assignée à plusieurs employés ou
    sous-traitants. Même logique que ProjectPhaseAssignee."""

    __tablename__ = "project_task_assignees"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "employe_id", name="uq_task_assignee_employe"
        ),
        UniqueConstraint(
            "task_id",
            "sous_traitant_id",
            name="uq_task_assignee_sous_traitant",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("project_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employe_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    sous_traitant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sous_traitants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
