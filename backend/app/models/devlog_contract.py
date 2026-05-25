"""Contrat client — pôle Développement logiciel.

Modèle inspiré de PurchaseAgreement / Soumission côté Construction
(signature électronique via token public, signed_at / signed_name /
signed_ip pour la trace, statut envoyée → signée).

Le contrat peut être rattaché à une soumission (le contrat est alors
formalise l'accord d'une soumission acceptée), à un client et/ou à un
projet pour traçabilité.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


CONTRACT_STATUSES = ("brouillon", "envoye", "signe", "annule")


class DevlogContract(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_contracts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    soumission_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_soumissions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Corps du contrat (texte / Markdown léger) — rendu tel quel sur la
    # page de signature publique.
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="brouillon",
        server_default="brouillon", index=True,
    )

    # Token opaque pour la page publique de signature
    # (/sign-devlog/{token}). Régénérable.
    signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )

    # Trace de signature.
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    signed_ip: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    # --- Dépôt initial ----------------------------------------------------
    # Phil saisit le dépôt à exiger lors de la création du contrat
    # (souvent 50 % du forfait initial). NULL = pas de dépôt requis.
    # Quand le dépôt est marqué payé (manuellement par Phil après
    # virement / chèque), on stocke ici l'horodatage et le montant
    # effectivement reçu. Le couple « contrat signé + dépôt payé »
    # déclenche automatiquement le démarrage du projet
    # (voir ``services.devlog_project_provision``).
    deposit_required_cents: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    deposit_paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deposit_paid_amount_cents: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    def __repr__(self) -> str:
        return f"<DevlogContract(id={self.id}, title='{self.title}', status='{self.status}')>"
