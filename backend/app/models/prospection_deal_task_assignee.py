"""Table de jointure pour les assignations de tâches Pipeline.

Une tâche (ProspectionDealTask) peut être assignée à plusieurs
utilisateurs simultanément (réunion qui implique plusieurs
prospecteurs, etc.). On garde aussi `assignee_user_id` sur la
tâche comme « primary » (= premier de la liste) pour la compat
descendante avec les anciens consumers.
"""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProspectionDealTaskAssignee(Base):
    __tablename__ = "prospection_deal_task_assignees"

    task_id: Mapped[int] = mapped_column(
        ForeignKey("prospection_deal_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
