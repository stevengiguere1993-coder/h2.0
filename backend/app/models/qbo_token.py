"""Single-row QBO tokens table so the rotating refresh token survives
backend restarts without relying on the Render API.

Populated automatically par le flow OAuth (/api/v1/qbo/connect +
/api/v1/qbo/callback), qui sauvegarde refresh_token + realm_id +
company_name en un seul appel.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QboToken(Base):
    __tablename__ = "qbo_tokens"

    # There is only ever one row (id=1). We pin the PK to keep the
    # upsert semantics cheap.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    refresh_token: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Company id QBO (realmId retourné par le callback OAuth). Persisté
    # ici pour que le client QBO puisse retrouver la compagnie sans
    # passer par l'env, même après un redeploy.
    realm_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    # "sandbox" ou "production" — stocké par le callback d'après la
    # config du backend au moment de la connexion.
    environment: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    # CompanyInfo.CompanyName, récupéré juste après l'échange de code.
    # Optionnel : sert uniquement à l'affichage « Connecté à : X ».
    company_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # Id de l'utilisateur qui a initié la connexion (audit).
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
