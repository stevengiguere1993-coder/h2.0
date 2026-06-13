"""AutomationSetting — état activable d'une automatisation du registre.

Une ligne par automatisation contrôlable (`key` = clé du catalogue).
Absence de ligne = activé par défaut (fail-open). Permet d'activer /
couper une automatisation depuis le hub Réglages → Automatisations sans
redéploiement. Nouvelle table → créée par `create_all`.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AutomationSetting(Base):
    __tablename__ = "automation_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    # Config éditable (JSON) lue par le job — ex. {"cadence_days": 4}.
    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
