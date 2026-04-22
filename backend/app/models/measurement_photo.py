"""MeasurementPhoto — photos attached to a MeasurementSnapshot.

Used for:
 - documenting a site visit (photos avant travaux)
 - "mesure sur photo" (user calibrates a reference line, then draws
   measurement lines overlaid on the photo — annotations JSON stored
   next to the blob, computed length reflected in the parent
   MeasurementSnapshot.area_ft2 when applicable).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base


class MeasurementPhoto(Base):
    __tablename__ = "measurement_photos"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    measurement_id: Mapped[int] = mapped_column(
        ForeignKey("measurement_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Deferred so list queries don't drag the blob along.
    image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=False)
    )
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Canvas annotations: reference line + measurement lines, pixel
    # coordinates + real-world scale. Stored as JSON-encoded string so
    # we don't need a JSONB mapping. Example:
    # {
    #   "ref": {"p1":[x,y],"p2":[x,y],"len_ft": 2.5},
    #   "lines": [{"p1":[x,y],"p2":[x,y],"len_ft": 8.2, "label":"mur"}]
    # }
    annotations_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    uploaded_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
