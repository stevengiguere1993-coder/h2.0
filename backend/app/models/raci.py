"""Matrice RACI « Distribution des tâches » (Gestion d'entreprise).

Quatre tables :
- ``RaciPole``     : un pôle (groupe de lignes), gérable depuis la page.
- ``RaciPerson``   : une colonne — un compte Kratos (``user_id``).
- ``RaciActivity`` : une ligne (tâche), rattachée à un pôle (par libellé).
- ``RaciCell``     : l'intersection ligne × colonne → R / A / C / I.

Tables créées au démarrage par ``create_all``. La colonne ``user_id`` de
``raci_people`` (ajoutée après coup) est garantie par
``ensure_critical_columns``.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class RaciPole(Base, TimestampUpdateMixin):
    __tablename__ = "raci_poles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class RaciPerson(Base, TimestampUpdateMixin):
    __tablename__ = "raci_people"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Compte Kratos rattaché (les colonnes = des détenteurs de compte).
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Sous-titre (rôle / pôle), pré-rempli depuis le compte.
    subtitle: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class RaciActivity(Base, TimestampUpdateMixin):
    __tablename__ = "raci_activities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Pôle d'appartenance (libellé). Cascade au renommage d'un pôle.
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
    # Une seule lettre : R (Réalise) / A (Autorité) / C (Consulté) /
    # I (Informé).
    value: Mapped[str] = mapped_column(String(1), nullable=False)
