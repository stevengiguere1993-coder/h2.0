"""TeamsMeetingImport — trace d'une rencontre Teams importée.

Une ligne par évènement Teams traité par la synchro (cf.
:mod:`app.services.rencontre_teams_sync`). Sert à :
  - l'idempotence : un meeting déjà importé (ical_uid) n'est jamais
    retraité ;
  - le lien avec la fiche créée (``rencontre_id``) — permet au frontend
    de badger « importée de Teams » sans toucher au modèle Rencontre ;
  - le diagnostic (statut : imported / no_transcript).
"""

from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TeamsMeetingImport(Base, TimestampMixin):
    __tablename__ = "teams_meeting_imports"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # iCalUId Graph — identifiant stable de l'évènement (clé d'idempotence).
    ical_uid: Mapped[str] = mapped_column(
        String(512), nullable=False, unique=True, index=True
    )
    subject: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    organizer_email: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True
    )
    meeting_start: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    # "imported" (fiche créée avec transcription) | "no_transcript"
    # (meeting terminé sans transcription disponible — pas de fiche).
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="imported"
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    rencontre_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("rencontres.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
