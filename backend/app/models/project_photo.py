"""ProjectPhoto — a picture attached to a Project, uploaded from the
site by staff (scan or file)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base


class ProjectPhoto(Base):
    __tablename__ = "project_photos"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Blob deferred so lists only pay for the metadata.
    image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=False)
    )
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    uploaded_by_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
