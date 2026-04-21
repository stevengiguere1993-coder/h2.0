"""SalesTask — a to-do item in the CRM, attached to a prospect
(ContactRequest) or a Client. Supports recurrence and multiple
employee assignees.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Column,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# Simple association table (not a declarative model since we don't
# need extra columns beyond the FKs).
sales_task_assignees = Table(
    "sales_task_assignees",
    Base.metadata,
    Column(
        "task_id",
        Integer,
        ForeignKey("sales_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "employe_id",
        Integer,
        ForeignKey("employes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class SalesTask(Base):
    __tablename__ = "sales_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Kind: suivi / commander_materiel / rappel_rdv / autre
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="suivi", server_default="suivi"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )  # hex like "#3b82f6" or a named preset

    # Target — attached to either a prospect (contact_request) or a client.
    contact_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Scheduling
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    all_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    due_time: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True
    )  # "HH:MM" when all_day = false

    # Recurrence — "none" | "daily" | "weekly" | "monthly"
    recurrence: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default="none"
    )

    # Lifecycle
    done: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    done_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
