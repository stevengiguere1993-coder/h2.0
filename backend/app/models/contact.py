"""Contact transverse — rolodex unifié du groupe Horizon.

Ce modèle accueille les contacts qui n'ont pas leur propre table dédiée :
avocats, notaires, comptables externes, partenaires d'investissement
potentiels, professionnels transversaux, services ponctuels…

Les autres entités contact-like (sous_traitants, fournisseurs,
employés-partenaires, devlog_sous_traitants) restent dans leurs
tables d'origine — la page /entreprises/contacts les fédère en
lecture, mais l'édition fine reste sur leurs pages spécialisées.
"""

from typing import Optional

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


CONTACT_KINDS = (
    "professional",       # avocat, notaire, comptable externe, conseiller
    "partner",            # partenaire d'affaires, allié stratégique
    "investor_prospect",  # investisseur potentiel (pas encore engagé)
    "service",            # prestataire ponctuel (peintre, traducteur…)
    "other",
)


class Contact(Base, TimestampUpdateMixin):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Type haut-niveau (cf. CONTACT_KINDS). String libre pour permettre
    # l'ajout de nouveaux types sans migration.
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="professional",
        server_default="professional", index=True,
    )
    # Spécialité libre : « Avocat corporatif », « Comptable », « Notaire »,
    # « Architecte »… Sert au filtre côté UI.
    specialty: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Tags transverses pour filtrer (ex. ["construction", "immobilier"]).
    tags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        server_default="true", index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Contact(id={self.id}, name='{self.full_name}', kind='{self.kind}')>"
