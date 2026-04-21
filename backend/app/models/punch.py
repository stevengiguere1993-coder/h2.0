"""Punch (time entry) — replaces Monday 'Temps (PUNCH)' board."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class Punch(Base, TimestampUpdateMixin):
    __tablename__ = "punches"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    employe_id: Mapped[int] = mapped_column(
        ForeignKey("employes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Lets employees clock hours against a prospect before a project
    # exists — typically visits, quoting and soumission preparation.
    contact_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    hours: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)

    task: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    geolocation: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # 'lat,lng'
    approved: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
