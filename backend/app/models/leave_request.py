"""LeaveRequest — a time-off request submitted by an employee, pending
approval by an admin.

When approved, an AgendaEvent with event_type="conge" is created
automatically so the employee's time block is visible on the team
agenda and the system can refuse other assignments during that window.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LeaveStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    employe_id: Mapped[int] = mapped_column(
        ForeignKey("employes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # vacation / sick / personal — défaut « vacation » pour ne rien
    # casser des entrées existantes. Les sick days sont auto-approuvés
    # côté UI (l'employé déclare, l'admin n'a qu'à valider).
    kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="vacation",
        server_default="vacation",
        index=True,
    )

    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=LeaveStatus.PENDING.value,
        server_default=LeaveStatus.PENDING.value,
        index=True,
    )

    # Review metadata — set when approved/rejected.
    reviewed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # When approved, we create an AgendaEvent and link it here so we can
    # later cancel it if the leave is retroactively rejected/cancelled.
    agenda_event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("agenda_events.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
