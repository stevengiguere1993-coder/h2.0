"""IA personnelle par utilisateur (« chacun son IA », sept. 2026).

Vision Phil : chaque utilisateur branche SA clé API (Anthropic, OpenAI
ou Google) — pas de clé, pas d'IA. Les fonctions IA déclenchées par un
humain passent par SA clé ; un brief quotidien par utilisateur donne à
son IA la vision complète de Kratos (filtrée par SES permissions).
L'IA des appels (Groq, webhooks automatiques) n'est PAS touchée.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserAiConfig(Base):
    """La connexion IA personnelle d'un utilisateur (1 max)."""

    __tablename__ = "user_ai_configs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    #: anthropic | openai | gemini
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Clé API du FOURNISSEUR de l'utilisateur — jamais renvoyée en
    #: clair par l'API (masquée sk-…1234), même stockage que les autres
    #: intégrations de la plateforme.
    api_key: Mapped[str] = mapped_column(Text, nullable=False)
    #: Modèle préféré (vide = défaut du provider).
    model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    #: Brief quotidien activé pour cet utilisateur.
    brief_actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    last_test_ok: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )
    last_test_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UserAiBrief(Base):
    """Brief quotidien généré par l'IA PERSONNELLE d'un utilisateur —
    c'est la « mémoire » de son IA : injecté en contexte système dans
    ses appels IA suivants, et lisible dans « Mon IA »."""

    __tablename__ = "user_ai_briefs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    jour: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    contenu: Mapped[str] = mapped_column(Text, nullable=False)
    #: Le digest BRUT (données compilées, avant IA) — debug + rejeu.
    digest: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
