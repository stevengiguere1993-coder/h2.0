"""ServiceTemplate — a reusable "service" that can be dropped into a
soumission with its default items, pre-filled with prices.

Example: "Installation Dalle" → 3 items (Excavation, Fondation, Pose de
dalle) each with a default unit_price. Inserted into a soumission, each
child becomes a SoumissionItem.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ServiceTemplate(Base):
    __tablename__ = "service_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_unit: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )  # e.g. "ft²", "unité", "h"
    default_unit_price: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="true", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ServiceTemplateItem(Base):
    __tablename__ = "service_template_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("service_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    default_quantity: Mapped[float] = mapped_column(
        Numeric(12, 3), nullable=False, default=1
    )
    default_unit_price: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0
    )
