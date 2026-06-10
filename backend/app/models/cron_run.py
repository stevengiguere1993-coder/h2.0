"""CronRun — verrou d'idempotence pour les tâches planifiées.

Une ligne par job ; `last_run_at` = dernière exécution réussie/claimée.
Sert à empêcher qu'un même cron parte deux fois dans une courte fenêtre
(scheduler qui rejoue, double-clic, deux instances) — ce qui pouvait
provoquer des doubles courriels de rappel.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CronRun(Base):
    __tablename__ = "cron_runs"

    job_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
