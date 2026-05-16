"""Soumission (quote / estimate sent to a prospect or client)."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class SoumissionStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Soumission(Base, TimestampUpdateMixin):
    __tablename__ = "soumissions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    reference: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    # Target — either a ContactRequest or a Client
    contact_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Amounts (in CAD)
    subtotal: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    tps: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    tvq: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    total: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SoumissionStatus.DRAFT.value, index=True
    )
    # Type de soumission : "forfaitaire" (montant fixe garanti) ou
    # "estime" (estimation à confirmer / refacturable selon réalité).
    # Influence l'affichage côté UI et le wording dans le PDF.
    pricing_kind: Mapped[str] = mapped_column(
        String(16), nullable=False,
        default="forfaitaire", server_default="forfaitaire",
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    pdf_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Internal-only notes (staff annotations, refusal reasons, margin
    # hints). Never rendered on the client PDF or public page.
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Client-facing note rendered on the soumission PDF and the public
    # signing page. Use this for "paiement 50 % à la signature, solde
    # à la fin des travaux" type wording.
    client_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # QuickBooks Online linkage (populated by sync service)
    qbo_estimate_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    qbo_doc_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    qbo_sync_token: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Public e-signature flow — the token is embedded in the email
    # link sent to the client; visiting the URL allows them to see
    # the PDF and accept without a portal account.
    signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    signed_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    signed_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Drawn signature captured from the public acceptance page. Stored
    # as raw PNG bytes; deferred so lists don't pay the cost.
    signature_image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    signature_image_content_type: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )

    # Property address captured at soumission time so the PDF + public
    # view always show the job location (may differ from the client's
    # billing address).
    property_address: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )

    # Quand l'utilisateur supprime explicitement le projet rattaché à
    # cette soumission, on met ce flag à True pour empêcher le backfill
    # de re-provisionner le projet à chaque démarrage du serveur. Sans
    # ce flag, le projet « ressuscite » à chaque cold-start Render.
    project_skip_backfill: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Nature du document : "quote" (devis classique avec lignes de
    # prix) ou "contract" (contrat d'entreprise APCHQ personnalisé
    # Horizon — prix coûtant majoré, clauses, signatures des 2 parties).
    # Un contrat réutilise toute l'infra soumission (référence, client,
    # e-signature, provisionnement projet/facture) mais ses champs
    # structurés vivent dans contract_data.
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="quote", server_default="quote"
    )
    # Données structurées du contrat d'entreprise (JSON sérialisé) :
    # responsable du projet, type de travaux, prestation, services,
    # exclusions, prix coûtant majoré (5.1/5.2), versements (6.2),
    # intérêts (6.4), élection de domicile, etc. NULL pour un devis.
    contract_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Signature de l'entrepreneur (Horizon) — le chargé de projet signe
    # pour la compagnie AVANT l'envoi au client. La signature du client
    # réutilise les champs signed_name / signature_image ci-dessus.
    contractor_signed_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    contractor_signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    contractor_signed_ip: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    contractor_signature_image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    contractor_signature_image_content_type: Mapped[Optional[str]] = (
        mapped_column(String(100), nullable=True)
    )
    # Jeton de signature de l'entrepreneur : le chargé de projet
    # reçoit par courriel un lien public /contrat-signature/{token}
    # pour signer le contrat AVANT son envoi au client.
    contractor_signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )

    # Suivi d'ouverture du lien public par le client (premier accès +
    # compteur de visites). Sert à afficher « Ouverte le {date} » côté
    # admin pour savoir si le client a regardé la soumission avant de
    # signer.
    client_opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    client_open_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Suivi d'ouverture du lien public par le chargé de projet
    # (signature entrepreneur). Même usage que ci-dessus côté Horizon.
    contractor_opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    contractor_open_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

