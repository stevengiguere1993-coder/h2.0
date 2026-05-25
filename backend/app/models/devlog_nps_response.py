"""Réponses NPS post-livraison — pôle Développement logiciel.

Chaque ligne représente une demande de feedback envoyée à un client 7
jours après la livraison de son projet (``DevlogProject.status='livre'``,
``delivered_at`` posé par event listener du modèle).

Flow :
    1. ``devlog_nps_dispatch`` job → crée la row + envoie un email avec
       un lien vers ``/devlog/nps/{token}`` (page publique sans auth).
    2. Le client ouvre le lien → ``opened_at`` est posé (best-effort).
    3. Le client soumet le formulaire → ``score`` + ``comment`` +
       ``submitted_at`` posés. Une seule soumission par token.

Le token est opaque (32 octets URL-safe via ``secrets.token_urlsafe``).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class DevlogNpsResponse(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_nps_responses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    project_id: Mapped[int] = mapped_column(
        ForeignKey("devlog_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Token opaque (URL-safe, ~43 chars pour 32 octets).
    token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )

    # Horodatage d'envoi de l'email NPS (toujours posé à la création).
    email_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Première ouverture de la page publique (best-effort, via le GET).
    opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 0 (pas du tout probable de recommander) à 10 (très probable).
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<DevlogNpsResponse(id={self.id}, project_id={self.project_id}, "
            f"score={self.score})>"
        )
