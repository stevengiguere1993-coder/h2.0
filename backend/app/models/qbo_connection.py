"""Connexions QuickBooks MULTI-compagnies (phase 1, 2026-07-22).

Une ligne par « scope » (pôle) : ``entreprise`` (Gestion d'entreprise),
``immobilier`` (Gestion locative)… Le pôle Construction, lui, reste sur
la table historique ``qbo_tokens`` (ligne unique id=1) : son chemin de
code n'est PAS touché — l'intégration QBO d'Horizon est trop critique
pour risquer une migration. Les nouveaux scopes utilisent cette table
via ``get_qbo(scope)``.

La MÊME app Intuit (client_id/secret env) sert toutes les connexions :
Intuit permet de connecter plusieurs compagnies avec une seule app —
chaque OAuth donne son propre realmId + refresh_token.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Scopes de connexion acceptés (hors construction = legacy qbo_tokens).
QBO_CONNECTION_SCOPES = ("entreprise", "immobilier")


class QboConnection(Base):
    __tablename__ = "qbo_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    #: "entreprise" | "immobilier" — une connexion max par scope.
    scope: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True
    )
    refresh_token: Mapped[str] = mapped_column(String(2048), nullable=False)
    realm_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    environment: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    company_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    connected_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    connected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
