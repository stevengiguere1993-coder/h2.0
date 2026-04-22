"""MeasurementSnapshot — a saved polygon measurement (area / wall
surface) tied to a client or a prospect.

Captured during a site visit using the map tool, stored once, and
reusable across many soumissions / bons de travail / projects.
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


class MeasurementSnapshot(Base):
    __tablename__ = "measurement_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Tied to either a client or a prospect (or both — when a prospect
    # converts to client we keep both refs so the history is intact).
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    label: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # "horizontal" (toiture/terrain/dalle — area of the polygon) or
    # "vertical" (mur — perimeter × wall_height).
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="horizontal"
    )
    area_ft2: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0
    )
    perimeter_ft: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    wall_height_ft: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    # Polygon coordinates as a JSON-encoded string list of {lat, lng}.
    # Kept as TEXT so we don't need a JSONB-aware mapping; round-trip
    # is enough for re-rendering.
    coords_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Geocoded address centroid for the map preview when re-opened.
    address: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )

    captured_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
