"""BonTask — tâche cochable d'un bon de travail.

Retour 2026-09-12, point 12 : les bons de travail d'un même lieu peuvent
être FUSIONNÉS en un seul bon qui porte plusieurs tâches à cocher (une
par bon d'origine, ou saisies à la main). Quand toutes les tâches sont
cochées, le bon interne se classe automatiquement « Complété — à
refacturer » ; le classement manuel reste toujours possible.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class BonTask(Base, TimestampUpdateMixin):
    __tablename__ = "bon_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    bon_id: Mapped[int] = mapped_column(
        ForeignKey("bons_travail.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    done_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    done_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Référence du bon d'origine quand la tâche vient d'une fusion
    # (trace : « d'où vient ce travail ? »). NULL = tâche saisie à la main.
    source_bon_reference: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
