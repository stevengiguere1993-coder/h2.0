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

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Text, func
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

    # Capture d'écran optionnelle attachée au signalement.
    # Stocké en BYTEA pour rester self-hosted (pas de S3 ici).
    # Limite côté API à ~4 MB pour éviter les abus.
    screenshot_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    screenshot_content_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    # Notes de résolution — saisies par l'admin/owner après avoir
    # traité le bug (« qu'est-ce qui causait ça, qu'est-ce qu'on a
    # fait pour régler »). Devient une référence pour la base de
    # connaissances. Visible seulement dans le panneau admin.
    resolution_notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Historique du traitement (Steven, 2026-11-13 : « section historique,
    # bug accepté ou refusé avec la note, date de la gestion du bug »).
    # ``section`` = volet / page concernée (déduite de la page du
    # signalement, modifiable au traitement) ; ``traite_le`` = date de la
    # dernière décision (accepté, refusé, réglé) ; ``traite_par`` =
    # courriel de la personne qui l'a prise.
    section: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    traite_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    traite_par: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
