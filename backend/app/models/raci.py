"""Matrice RACI « Distribution des tâches » (Gestion d'entreprise).

Trois tables simples :
- ``RaciPerson``   : une colonne (partenaire ou employé).
- ``RaciActivity`` : une ligne (tâche), regroupée par ``pole``.
- ``RaciCell``     : l'intersection ligne × colonne → R / A / C / I.

Tables créées au démarrage par ``create_all`` (pas d'Alembic).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class RaciPerson(Base, TimestampUpdateMixin):
    __tablename__ = "raci_people"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Sous-titre libre (ex. « Construction », « Comptabilité »).
    subtitle: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class RaciActivity(Base, TimestampUpdateMixin):
    __tablename__ = "raci_activities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Pôle d'appartenance (ex. « Gestion locative »). Texte libre pour
    # rester souple si les pôles évoluent.
    pole: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default=""
    )
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class RaciCell(Base, TimestampUpdateMixin):
    __tablename__ = "raci_cells"
    __table_args__ = (
        UniqueConstraint("activity_id", "person_id", name="uq_raci_cell"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    activity_id: Mapped[int] = mapped_column(
        ForeignKey("raci_activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_id: Mapped[int] = mapped_column(
        ForeignKey("raci_people.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Une seule lettre : R (Réalise) / A (Approuve) / C (Consulté) /
    # I (Informé).
    value: Mapped[str] = mapped_column(String(1), nullable=False)
