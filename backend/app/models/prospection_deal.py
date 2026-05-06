"""Pipeline des deals — suivi style Monday.com.

Chaque deal correspond à une opportunité d'achat / négociation sur
un immeuble repéré. On démarre minimal (adresse + priorité) ; les
champs supplémentaires (statut, étape, notes, montant, etc.) seront
ajoutés au fil des itérations.

Le tri d'affichage du Pipeline se fait par priorité décroissante :
urgent → eleve → moyenne → en_attente → a_venir.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# Ordre canonique des priorités. Le champ stocke la valeur textuelle
# pour rester lisible en SQL ; le tri côté API/frontend mappe vers
# un rang numérique.
PRIORITY_ORDER = ("urgent", "eleve", "moyenne", "en_attente", "a_venir")


class ProspectionDeal(Base):
    __tablename__ = "prospection_deals"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="moyenne",
        server_default="moyenne",
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
