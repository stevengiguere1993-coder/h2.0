"""Listes de prospection — segments sauvegardés.

Une « liste » regroupe N leads selon des critères (ex: « Multi 6-12
portes Plateau », « Corporations Hochelaga année <1970 »). Permet
au prospecteur de choisir une liste et travailler ses leads dedans
sans refaire les filtres à chaque fois.

Inspiré de DealMachine / PropStream.

Une liste peut être :
- Manuelle : on ajoute/retire les leads à la main
- Construite via le List Builder (filtres) : on capture les critères
  + on matérialise les leads correspondants au moment de la création.
  Si l'utilisateur veut rafraîchir, il appelle l'endpoint de rebuild.

Les listes appartiennent à l'utilisateur qui les crée. Tout manager+
peut voir / modifier les listes (collaboration intra-équipe).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class ProspectionLeadList(Base, TimestampUpdateMixin):
    __tablename__ = "prospection_lead_lists"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Critères du List Builder, JSON-encodés. Permet de re-construire
    # la liste plus tard avec les mêmes filtres. Schéma :
    #   {"status": "a_visiter", "kind": "multilogement",
    #    "city": "Montréal", "min_logements": 6, "max_logements": 12,
    #    "owner_kind": "corporation", "min_score": 50, ...}
    criteria_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class ProspectionLeadListMember(Base):
    """Association list ↔ lead (N:N)."""

    __tablename__ = "prospection_lead_list_members"

    list_id: Mapped[int] = mapped_column(
        ForeignKey(
            "prospection_lead_lists.id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("prospection_leads.id", ondelete="CASCADE"),
        nullable=False,
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        PrimaryKeyConstraint("list_id", "lead_id"),
    )
