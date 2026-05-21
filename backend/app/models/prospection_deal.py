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

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# Ordre canonique des priorités. Conservé pour la compat des données
# existantes (anciennes pastilles urgent/élevé/etc.) ; l'UI ne les
# expose plus depuis qu'on aligne les Deals sur la mise en page
# entreprise (chaque Deal = sa propre fiche + ses tâches).
PRIORITY_ORDER = (
    "urgent",
    "eleve",
    "moyenne",
    "a_venir",
    "termine",
    "abandonne",
)


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
    # Ordre d'affichage dans la sidebar Pipeline. Modifiable par
    # drag & drop (même mécanisme que `entreprises.position`).
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", index=True
    )

    # URL du dossier Google Drive du deal. Bouton « Drive » dans le
    # header de la fiche y mène. NULL = pas configuré.
    drive_folder_url: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True
    )

    # Lien optionnel vers la fiche d'analyse qui a généré ce deal
    # (via le bouton « Pipeline » sur la page Analyses des leads).
    # NULL si le deal a été créé manuellement.
    lead_analysis_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("lead_analyses.id", ondelete="SET NULL"),
        nullable=True,
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
