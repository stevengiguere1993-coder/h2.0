"""Table de jointure tâche d'entreprise ↔ entreprises SUPPLÉMENTAIRES.

Une tâche appartient à une entreprise principale (``entreprise_taches.
entreprise_id``) et peut concerner d'autres entreprises (Phil 2026-10-03 :
« pouvoir y mettre plusieurs entreprises »). Cette table porte les
entreprises secondaires ; l'API expose ``entreprise_ids`` = [principale]
+ secondaires.
"""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EntrepriseTacheEntreprise(Base):
    __tablename__ = "entreprise_tache_entreprises"

    tache_id: Mapped[int] = mapped_column(
        ForeignKey("entreprise_taches.id", ondelete="CASCADE"),
        primary_key=True,
    )
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        primary_key=True,
    )
