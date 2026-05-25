"""Membre assigne a un projet de developpement - pole Developpement logiciel.

Un membre peut etre :
  - un User interne (employe / dev) : user_id renseigne,
    sous_traitant_id NULL ;
  - un DevlogSousTraitant (freelance externe) : sous_traitant_id
    renseigne, user_id NULL.

L'un des deux doit etre renseigne (contrainte applicative cote
endpoints). On garde role + hourly_rate optionnels pour permettre
un override par projet (ex. un dev paye plus cher sur un mandat).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DevlogProjectMember(Base):
    __tablename__ = "devlog_project_members"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("devlog_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    sous_traitant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_sous_traitants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Role libre (ex. "Lead dev", "Design", "QA"). NULL = pas precise.
    role: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Override de taux horaire pour ce projet (CAD). NULL = on retombe
    # sur le taux par defaut du sous-traitant / employe.
    hourly_rate: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    added_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<DevlogProjectMember(id={self.id}, "
            f"project_id={self.project_id}, user_id={self.user_id}, "
            f"sous_traitant_id={self.sous_traitant_id})>"
        )
