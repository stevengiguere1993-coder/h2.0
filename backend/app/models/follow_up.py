"""FollowUp — entrée du journal de suivi commercial.

Une seule table polymorphique pour suivre les interactions sur un
prospect (ContactRequest) ou une soumission (Soumission). Les
entrées sont créées automatiquement par les hooks (nouveau lead,
soumission envoyée) ou manuellement par le commercial après chaque
appel ou courriel.

Champs clés :
- subject_type / subject_id : ce qu'on suit
- kind / direction / outcome : nature de l'interaction
- performed_at + performed_by_user_id : qui, quand
- next_action_at + next_action_label : prochaine relance prévue
  (NULL quand le suivi est terminé : won, lost, not_interested)
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FollowUp(Base):
    __tablename__ = "follow_ups"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # « prospect » ou « soumission » — pas de FK car polymorphique
    subject_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    subject_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # call / email / sms / visite / note / auto
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # outbound / inbound (côté staff vers client = outbound)
    direction: Mapped[str] = mapped_column(
        String(16), nullable=False, default="outbound"
    )
    # reached / voicemail / no_answer / interested / not_interested /
    # won / lost / pending / scheduled
    outcome: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    performed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Quand la prochaine relance doit avoir lieu. NULL = aucune relance
    # prévue (cycle terminé). Indexé pour le cron qui scanne les
    # « overdue ».
    next_action_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    next_action_label: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    # Marqué True une fois qu'une notif « overdue » a été envoyée pour
    # cette entrée — évite de spammer la cloche toutes les heures.
    overdue_notified: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
