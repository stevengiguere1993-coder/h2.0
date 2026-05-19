"""GeocodedAddress — cache des coordonnées géo d'une adresse texte.

Évite de spammer Nominatim (1 req/sec maximum) à chaque calcul de
travel time. Une fois qu'on a géocodé « 1234 rue X, Montréal », on
garde lat/lng pendant 6 mois (les adresses bougent rarement).

Clé de cache : version normalisée (lowercase + collapsed whitespace)
de l'adresse — évite les doublons pour des variantes triviales.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GeocodedAddress(Base):
    __tablename__ = "geocoded_addresses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    address_key: Mapped[str] = mapped_column(
        String(500), nullable=False, unique=True, index=True
    )
    address_original: Mapped[str] = mapped_column(String(500), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="nominatim"
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # Adresse normalisée renvoyée par le géocodeur (utile pour
    # comparaisons / affichage). Optionnel.
    canonical: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
