"""Rencontre (conseil d'actionnaires / retraite stratégique) — trace
des discussions multi-entreprises avec sections par topic.

Une Rencontre :
  - regroupe plusieurs `entreprises` concernées (JSON list d'ids)
  - contient plusieurs `RencontreSection` (= topics) avec leur
    transcript brut + résumé IA structuré
  - peut avoir un résumé global cross-sections

Cas d'usage : retraite stratégique de 2-3 jours où on touche plusieurs
sociétés ; on veut tout enregistrer (dictée + audio uploadé transcrit
via Whisper), résumer par Claude, et garder une trace.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class RencontreStatus(str, Enum):
    DRAFT = "draft"
    DONE = "done"


class Rencontre(Base, TimestampUpdateMixin):
    __tablename__ = "rencontres"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    meeting_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Participants (texte libre OU JSON liste, on garde texte simple).
    attendees: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # IDs des entreprises concernées — JSON `[12, 17, 31]`. Permet à
    # une rencontre de toucher plusieurs sociétés sans table jointure.
    entreprise_ids_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # Notes libres pour le préparateur de la rencontre.
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Résumé global IA (généré une fois toutes les sections résumées).
    global_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=RencontreStatus.DRAFT.value,
        server_default=RencontreStatus.DRAFT.value,
        index=True,
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class RencontreSection(Base, TimestampUpdateMixin):
    """Une section = un topic discuté pendant la rencontre. Une retraite
    de 2-3 jours = plusieurs sections (planification stratégique,
    finances, RH, marketing, etc.)."""

    __tablename__ = "rencontre_sections"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    rencontre_id: Mapped[int] = mapped_column(
        ForeignKey("rencontres.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)

    # Texte brut de la section (dicté/tapé/transcrit depuis audio).
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Résumé IA structuré JSON (décisions, actions, suivis, risques)
    # pour pouvoir l'afficher proprement côté UI.
    ai_summary_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
