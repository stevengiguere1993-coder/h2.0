"""Table de jointure tâche Pipeline ↔ immeuble.

Une tâche peut référencer 0, 1 ou plusieurs immeubles (visite à
préparer, dossier de financement à finaliser pour tel triplex…).
La cardinalité est gérée par le frontend via un picker multi-select
dans la fiche détaillée de la tâche.
"""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProspectionDealTaskImmeuble(Base):
    __tablename__ = "prospection_deal_task_immeubles"

    task_id: Mapped[int] = mapped_column(
        ForeignKey("prospection_deal_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        primary_key=True,
    )
