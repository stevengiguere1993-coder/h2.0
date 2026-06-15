"""Étape d'une séquence de relance (cadence) configurable.

Une seule séquence GLOBALE, partagée par tous les leads/clients : ex.
« Appel J0 → Appel J+2 → Courriel J+2 (tentatives sans réponse) ». Les
étapes sont ordonnées par `position`. L'utilisateur les personnalise dans
l'UI Relances ; le moteur de relances les exécute.
"""

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class CadenceStep(Base, TimestampUpdateMixin):
    __tablename__ = "cadence_steps"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Ordre de l'étape dans la séquence (0 = première).
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Canal de l'action : "call" | "email" | "sms".
    channel: Mapped[str] = mapped_column(
        String(16), nullable=False, default="call"
    )
    # Délai (en jours) AVANT cette étape, compté depuis l'étape
    # précédente (ou depuis l'entrée en cadence pour la première).
    delay_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # Libellé visible (ex. « Premier appel », « Courriel de relance »).
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    # Pour une étape « email » : gabarit à envoyer (variables {{nom}}…).
    email_template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("email_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
