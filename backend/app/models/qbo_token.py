"""Single-row QBO tokens table so the rotating refresh token survives
backend restarts without relying on the Render API.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QboToken(Base):
    __tablename__ = "qbo_tokens"

    # There is only ever one row (id=1). We pin the PK to keep the
    # upsert semantics cheap.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    refresh_token: Mapped[str] = mapped_column(String(2048), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
