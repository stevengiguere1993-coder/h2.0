"""SoumissionItem — line item attached to a Soumission (quote/estimate)."""

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class SoumissionItem(Base, TimestampUpdateMixin):
    __tablename__ = "soumission_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    soumission_id: Mapped[int] = mapped_column(
        ForeignKey("soumissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Display order inside the soumission (0-based)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # e.g. "h", "unite", "jour"
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # Cost to Horizon per unit (e.g. Rona list price, subcontractor
    # rate). INTERNAL ONLY — never included in the public soumission
    # JSON / PDF sent to the client. Used to compute projected margin.
    cost_per_unit: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, server_default="0"
    )

    # Per-item tax toggles so the quote can mix taxable services
    # (e.g. main-d'œuvre) with non-taxable line items (e.g. rabais).
    tps_applicable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    tvq_applicable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # "service" (default), "frais" (no-tax fee), "rabais" (negative discount).
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="service", server_default="service"
    )
