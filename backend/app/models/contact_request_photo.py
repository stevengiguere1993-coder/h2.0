"""ContactRequestPhoto — photos joined to a public contact form
submission.

Le formulaire de contact public permet au prospect d'attacher
jusqu'à 5 photos (avant travaux, dégâts, inspirations…). On les
stocke en base (BYTEA déféré comme pour MeasurementPhoto) pour que
l'équipe interne les retrouve dans la fiche du prospect — même si
notre intégration Monday.com est en panne ou plus utilisée.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base


class ContactRequestPhoto(Base):
    __tablename__ = "contact_request_photos"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    contact_request_id: Mapped[int] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=False)
    )
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
