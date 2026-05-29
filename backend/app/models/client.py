"""Client model — a prospect that accepted a soumission or was
created manually by staff."""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project


class Client(Base, TimestampMixin):
    """Active client (post-conversion from prospect)."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Client de type entreprise (vs particulier). Quand vrai, on peut
    # saisir un représentant (personne-ressource) affiché sur les
    # documents (« À l'attention de … »).
    is_company: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
    representative: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # Langue du client : « fr » (défaut) ou « en ». Détermine la langue
    # de l'état de compte qui lui est transmis.
    language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="fr"
    )

    # Link back to the original prospect (when the client was
    # converted from an accepted soumission). NULL when staff created
    # the client directly.
    contact_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # QuickBooks Online customer id (Customer.Id). Rempli par le
    # bouton « Envoyer vers QuickBooks » sur la fiche client ; sert à
    # éviter les doublons au prochain push et affiche le badge « QB ✓ ».
    qbo_customer_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )

    # Relationships
    projects: Mapped[List["Project"]] = relationship(
        "Project",
        back_populates="client",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Client(id={self.id}, name='{self.name}')>"
