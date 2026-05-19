"""LeaChatSession — conversation Léa-Web (chat texte public sur le site).

Une session = une conversation chat. On stocke :
  - le token public (UUID utilisé comme clé côté browser localStorage)
  - les coordonnées du visiteur (au fur et à mesure que Léa les collecte)
  - l'état conversationnel (intake_data, proposed_slots) pour pouvoir
    booker à la fin
  - le lien vers le ContactRequest créé (une fois l'intake validé)

Pas d'auth — l'accès se fait par token uniquement. Les sessions
expirent après 30 jours d'inactivité (cleanup cron à ajouter).
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


class LeaChatSession(Base):
    __tablename__ = "lea_chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # UUID public stocké côté browser dans localStorage. Permet de
    # retrouver la conversation au refresh ou changement de page.
    token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    # Coordonnées visiteur collectées au fil de la conversation
    visitor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    visitor_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    visitor_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    lang: Mapped[str] = mapped_column(String(8), nullable=False, default="fr-CA")
    # JSON sérialisé : intake_data + proposed_slots (cross-turn state).
    session_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Page d'origine (utile pour KPI / source attribution).
    landing_page: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Lien CRM une fois qu'on a créé le lead.
    contact_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # AgendaEvent créé si la session a abouti à un RV booké.
    booked_event_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class LeaChatMessage(Base):
    __tablename__ = "lea_chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("lea_chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 'user' | 'assistant' | 'system'
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON pour structured data : { proposed_slots: [...], intent: ..., ... }
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
