"""Kratos — table inbox/historique du « secrétaire virtuel ».

Chaque entrée capture : ce que l'utilisateur a dit/collé à Kratos,
l'intent extrait par l'IA (Claude), l'objet créé ou rattaché, et un
statut (queued / routed / needs_review / discarded).

Permet à la fois :
  - de garder la trace de tout ce qui a été dit à Kratos,
  - de pouvoir interroger « qu'est-ce que j'ai dit à Kratos cette
    semaine ? »,
  - de retourner manuellement classer une entrée si l'IA s'est
    trompée (status=needs_review → confirm/discard).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KratosIntentKind(str, Enum):
    ENTREPRISE_TASK = "entreprise_task"
    LEAD_NOTE = "lead_note"
    PROSPECTION_LEAD_NOTE = "prospection_lead_note"
    NOTE = "note"  # générique, stocké dans l'inbox uniquement
    UNKNOWN = "unknown"


class KratosMessageStatus(str, Enum):
    ROUTED = "routed"           # IA a routé, action appliquée
    NEEDS_REVIEW = "needs_review"  # IA pas sûre, attend confirmation
    DISCARDED = "discarded"     # rejeté par l'utilisateur


class KratosMessage(Base):
    __tablename__ = "kratos_messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Texte original dicté/tapé/collé par l'utilisateur.
    original_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Intent reconnu par Claude (parmi KratosIntentKind).
    intent_kind: Mapped[str] = mapped_column(
        String(48), nullable=False, default=KratosIntentKind.NOTE.value
    )
    # JSON brut retourné par Claude (résumé, entités, suggestions).
    # Garde la trace si on veut ré-router plus tard.
    intent_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Résumé court de l'entrée (généré par Claude) — sert d'affichage
    # dans l'inbox.
    summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Objet créé/rattaché : type + id (libre). Ex.
    #   target_type="entreprise_tache", target_id=42
    #   target_type="lead_analysis",  target_id=17
    target_type: Mapped[Optional[str]] = mapped_column(
        String(48), nullable=True, index=True
    )
    target_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=KratosMessageStatus.ROUTED.value,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
