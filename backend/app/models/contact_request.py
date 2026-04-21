"""
ContactRequest model for landing-page contact form submissions.

This is the CRM table that receives every contact request submitted from
the public website. It replaces the Monday.com "Demande de contact" board.
"""

from enum import Enum
from typing import Optional

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class ProjectType(str, Enum):
    """Services offered by Horizon Services Immobiliers."""

    SALLE_BAIN = "salle_bain"
    CUISINE = "cuisine"
    MULTILOGEMENT = "multilogement"
    RENOVATION_COMPLETE = "renovation_complete"
    AUTRE = "autre"


class ContactRequestStatus(str, Enum):
    """Pipeline status for a contact request in the internal CRM."""

    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    QUOTED = "quoted"
    WON = "won"
    LOST = "lost"
    SPAM = "spam"


class ContactRequest(Base, TimestampUpdateMixin):
    """
    Contact request submitted from the public website.

    Every request is stored here first. Staff triage from the admin zone.
    Never auto-created in Monday (we are migrating off Monday).
    """

    __tablename__ = "contact_requests"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Identity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Project
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    project_type: Mapped[str] = mapped_column(String(32), nullable=False, default=ProjectType.AUTRE.value)
    budget_range: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Context
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="fr")
    source: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Consent (Loi 25 / Québec + RGPD-style)
    gdpr_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    marketing_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Pipeline
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ContactRequestStatus.NEW.value, index=True
    )
    # Free-form kanban column label so the staff can define their own
    # CRM columns (e.g. "En attente de pièce", "Rappel à faire", "À
    # visiter"). When null we bucket by `status` instead.
    kanban_column: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    internal_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ContactRequest(id={self.id}, email='{self.email}', status='{self.status}')>"
