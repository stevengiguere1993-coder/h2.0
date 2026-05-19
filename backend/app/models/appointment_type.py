"""AppointmentType — type de rendez-vous configurable avec durée
par défaut, buffer de préparation et rôles autorisés.

Permet à l'agenda de construction de :
  - auto-remplir la durée au moment de créer un RV (1h30 pour une
    évaluation de soumission, 30 min pour une visite de chantier…)
  - ajouter un buffer de prép avant le RV (le closer doit consulter
    la fiche, préparer son tablette, etc.)
  - filtrer les users assignables selon leur rôle fonctionnel
    (UserBusinessRole) — un closer pour les évaluations, un chargé
    de projet pour les visites de chantier.

Phase 1 : seed avec 4 types par défaut (évaluation, visite chantier,
réunion interne, inspection finale). L'admin peut ajouter/modifier
depuis l'UI plus tard.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppointmentType(Base):
    __tablename__ = "appointment_types"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Slug stable (« evaluation_soumission », « visite_chantier ») pour
    # référencer le type dans le code (Léa, automations, etc.).
    slug: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Durée du rendez-vous chez le client (minutes).
    default_duration_min: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60
    )
    # Buffer de préparation AVANT le RV (ex. closer qui révise sa fiche).
    prep_buffer_min: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # Liste de rôles fonctionnels autorisés à prendre ce RV
    # (UserBusinessRole.role_kind séparés par virgule). NULL = tous.
    # Ex. : « closer » pour évaluations, « charge_projet » pour visites.
    allowed_roles_csv: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # Couleur visuelle pour l'agenda (hex sans #).
    color: Mapped[str] = mapped_column(String(8), nullable=False, default="0ea5e9")
    # Type qui implique un déplacement chez le client (active le calcul
    # de transit en Vague 3).
    requires_travel: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
