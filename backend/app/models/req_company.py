"""Cache local des corporations québécoises (Registraire des entreprises).

Source : « Données ouvertes du Registraire des entreprises » du Québec
(CSV/ZIP mis à jour quotidiennement, ~1 M corporations).

Le téléchargement direct du ZIP par notre backend est bloqué par
Cloudflare (challenge bot). L'utilisateur télécharge donc le ZIP via
son navigateur, l'uploade dans le backend une fois, et on ingère
le contenu dans cette table pour permettre des lookups SQL rapides
par nom ou par NEQ depuis le module Prospection.

Ré-import idempotent : ON CONFLICT (neq) DO UPDATE.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReqCompany(Base):
    __tablename__ = "req_companies"

    # NEQ : 10 chiffres unique au Québec.
    neq: Mapped[str] = mapped_column(String(16), primary_key=True)

    nom: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    statut: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    forme_juridique: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True
    )
    date_immatriculation: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )

    # Adresse du domicile / siège (utile pour matcher avec un lead)
    adresse: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ville: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    code_postal: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )

    # Téléphone du siège social — publié dans le CSV REQ.
    # Source légitime : information d'affaires publique.
    telephone: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )

    # Nom normalisé pour recherche insensible aux accents/casse.
    nom_normalized: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, index=True
    )

    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_req_adresse", "adresse"),
        Index("ix_req_ville", "ville"),
    )
