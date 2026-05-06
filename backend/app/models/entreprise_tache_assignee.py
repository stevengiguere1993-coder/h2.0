"""Table de jointure pour les assignations multi-personnes des
tâches d'entreprise.

Une tâche peut être assignée à plusieurs utilisateurs simultanément
(meeting d'équipe, projet collectif…). Le scalaire `assignee_user_id`
sur EntrepriseTache est conservé en « primary » (= premier de la
liste) pour la compat descendante.
"""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EntrepriseTacheAssignee(Base):
    __tablename__ = "entreprise_tache_assignees"

    tache_id: Mapped[int] = mapped_column(
        ForeignKey("entreprise_taches.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
