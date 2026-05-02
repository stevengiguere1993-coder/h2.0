"""Entreprise — entité d'affaire (HSI, sociétés sœurs, partenariats…).

Sert de tronc au volet Gestion d'entreprises : chaque tâche, projet
ou suivi appartient à une entreprise. Les utilisateurs peuvent être
associés à plusieurs entreprises via EntreprisePartner avec un rôle
et un pourcentage d'ownership.
"""

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class Entreprise(Base, TimestampUpdateMixin):
    __tablename__ = "entreprises"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )

    # NEQ (numéro d'entreprise du Québec). Permet le lien avec REQ.
    neq: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )

    # Catégorie : gestion / construction / immobilier / autre.
    # Influence l'icône et certains workflows.
    type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="gestion",
        server_default="gestion",
    )

    # Couleur d'accent pour l'UI (badge entreprise dans les listes
    # de tâches multi-entreprises). Format hex « #aabbcc ».
    color_accent: Mapped[str] = mapped_column(
        String(7), nullable=False, default="#7c3aed",
        server_default="#7c3aed",
    )

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Lien Monday : board source pour la synchronisation des tâches.
    # NULL = entreprise gérée nativement dans h2.0.
    monday_board_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    monday_board_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class EntreprisePartner(Base):
    """Association user × entreprise + ownership / rôle.

    Plusieurs partenaires peuvent posséder une entreprise (ex. 50/50
    Steven + Philippe). Le rôle décrit la fonction (associé,
    administrateur, gérant…).
    """

    __tablename__ = "entreprise_partners"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="associe",
        server_default="associe",
    )
    ownership_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
