"""FactureItem — line item attached to a Facture (client invoice)."""

from typing import Optional

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class FactureItem(Base, TimestampUpdateMixin):
    __tablename__ = "facture_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    facture_id: Mapped[int] = mapped_column(
        ForeignKey("factures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    # Catégorie de ligne (introduit pour tracker les extras hors
    # soumission — ex. main-d'œuvre supplémentaire, ajout en cours de
    # chantier). « service » = ligne standard chargée sur le contrat.
    # « extra » = ligne hors-contrat, ne réduit pas le « reste à
    # facturer » de la soumission et bonifie le profit réel quand
    # encaissée. « rabais » = ligne négative. « frais » = ligne sans
    # taxes (ex. frais de déplacement absorbés).
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="service", index=True
    )
