"""HelpRequest — bouton « Aide » dans l'app.

Deux types :
- `question` : la personne pose une question, on appelle Claude API et
  on stocke réponse pour traçabilité.
- `bug` : signalement d'erreur. Steven (owner) voit la liste dans
  Paramètres et peut accepter/rejeter. Quand il revient parler à
  Claude Code, il dit « regarde les bugs acceptés » et l'agent les
  fetch via /api/v1/help/reports/accepted.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HelpRequestKind(str, Enum):
    QUESTION = "question"
    BUG = "bug"


class HelpRequestStatus(str, Enum):
    PENDING = "pending"  # bug en attente de triage
    ACCEPTED = "accepted"  # bug accepté pour correction
    REJECTED = "rejected"  # bug rejeté (n'est pas un bug, doublon, etc.)
    RESOLVED = "resolved"  # bug réglé (Claude Code a livré le fix)
    ANSWERED = "answered"  # question répondue par Claude API


class HelpRequest(Base):
    __tablename__ = "help_requests"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=HelpRequestStatus.PENDING.value, index=True
    )

    message: Mapped[str] = mapped_column(Text, nullable=False)
    ai_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Contexte capturé automatiquement pour faciliter le debug
    context_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
