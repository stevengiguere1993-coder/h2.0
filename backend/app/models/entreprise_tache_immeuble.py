"""Table de jointure tâche d'entreprise ↔ immeuble.

Pendant identique à prospection_deal_task_immeubles côté Pipeline.
Une tâche peut concerner plusieurs immeubles (rénovation à coordonner
sur deux triplex de la même rue, etc.).
"""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EntrepriseTacheImmeuble(Base):
    __tablename__ = "entreprise_tache_immeubles"

    tache_id: Mapped[int] = mapped_column(
        ForeignKey("entreprise_taches.id", ondelete="CASCADE"),
        primary_key=True,
    )
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        primary_key=True,
    )
