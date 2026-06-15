"""État de la séquence de relance (cadence) POUR UN lead donné.

Un plan par lead (ContactRequest). `step_index` = prochaine étape à
exécuter dans la séquence globale ; `next_at` = quand cette étape est due.
Le moteur (cron) fait avancer le plan et l'arrête quand le lead répond ou
est engagé/clos.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class RelancePlan(Base, TimestampUpdateMixin):
    __tablename__ = "relance_plans"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Un seul plan par lead.
    contact_request_id: Mapped[int] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # Index (0-based) de la PROCHAINE étape à exécuter.
    step_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # Échéance de l'étape en cours.
    next_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # active | done | stopped
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", index=True
    )
