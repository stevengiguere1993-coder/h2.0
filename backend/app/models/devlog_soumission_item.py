"""Ligne (item) d'une soumission du pôle Développement logiciel.

Une soumission est composée de N lignes : feature, jour-personne,
forfait, abonnement, etc. Le total de la soumission est la somme des
totaux de ses lignes. Conserve une référence simple, sans tax pour
l'instant (à ajouter quand on branchera la TPS/TVQ comme Construction).
"""

from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class DevlogSoumissionItem(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_soumission_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    soumission_id: Mapped[int] = mapped_column(
        ForeignKey("devlog_soumissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    # Unité libre : "h", "jour", "forfait", "mois", etc.
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    quantity: Mapped[float] = mapped_column(
        Float, nullable=False, default=1, server_default="1"
    )
    unit_price: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )
    total: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<DevlogSoumissionItem(id={self.id}, soumission_id={self.soumission_id}, total={self.total})>"
