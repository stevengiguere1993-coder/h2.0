"""Single-row counters for sequential numbering of factures and
soumissions. Permet à l'administrateur de configurer les prochains
numéros pour s'aligner avec une suite QuickBooks existante.

Une seule ligne (id=1) qui contient les compteurs courants :
- next_facture_number : prochain numéro de facture à attribuer
- next_soumission_number : prochain numéro de devis à attribuer

Chaque création de facture/soumission lit le compteur, l'incrémente,
et grave la valeur sur la nouvelle ligne. Atomique côté DB grâce à
un UPDATE … RETURNING.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NumberingCounter(Base):
    __tablename__ = "numbering_counters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    next_facture_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    next_soumission_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    next_po_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
