"""Photos attachées à un ProspectionLead.

Stockées en BYTEA dans la DB (pas dans un object store) pour rester
sur la même infra Render simple. Si volume devient important on
migrera vers S3/R2.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base


class ProspectionLeadPhoto(Base):
    __tablename__ = "prospection_lead_photos"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("prospection_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Bytes du fichier — deferred pour ne pas charger l'image à
    # chaque SELECT du lead.
    content: Mapped[bytes] = deferred(
        mapped_column(LargeBinary, nullable=False)
    )
    caption: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
