"""ProjectPhase — a time-boxed stage of a Project.

Each project can be broken into ordered phases (e.g. Démolition,
Électricité, Plomberie, Finition). Each phase has a start date + a
duration in days, which drives the end date. ProjectTask rows can
optionally be attached to a phase via phase_id.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProjectPhase(Base):
    __tablename__ = "project_phases"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Duration in calendar days. End date is derived on the client side
    # as start_date + duration_days - 1 (so a 1-day phase spans exactly
    # its start_date). Nullable so half-defined phases are allowed while
    # the project is being sketched out.
    duration_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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
