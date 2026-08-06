"""eSign — signature électronique de documents (pôle Gestion d'entreprise).

Principe eversign/Xodo Sign ramené dans Kratos : on téléverse un PDF,
on le rattache à une entreprise du groupe, on choisit des signataires
(banque de contacts unifiée OU création manuelle prénom/nom/courriel),
on positionne visuellement des zones (signature, initiales, date auto,
texte) sur les pages, puis chaque signataire reçoit un lien public
opaque par courriel. Optionnel par signataire : authentification par
code SMS (Twilio) avant de pouvoir signer.

Suivi complet côté admin : envoi, ouvertures (compteur + horodatage),
code SMS vérifié, signature (IP + horodatage), refus. Quand tous les
signataires ont signé, le PDF final « aplati » est généré (zones
fusionnées dans les pages via reportlab + pypdf) avec une page d'audit
en annexe, puis envoyé par courriel à toutes les parties.

Tables créées par `ensure_esign_tables()` (app/db/session.py) — pas
d'Alembic, conformément au pattern du repo.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampMixin, TimestampUpdateMixin


class EsignDocumentStatus(str, Enum):
    """Cycle de vie d'un document à signer.

    - brouillon : téléversé, en préparation (signataires + zones)
    - envoye    : liens de signature partis — « document en cours »
    - complete  : tous les signataires ont signé — « document signé »
    - refuse    : au moins un signataire a refusé
    - annule    : annulé côté admin (liens désactivés)
    """

    BROUILLON = "brouillon"
    ENVOYE = "envoye"
    COMPLETE = "complete"
    REFUSE = "refuse"
    ANNULE = "annule"


class EsignFieldKind(str, Enum):
    """Types de zones posables sur les pages du PDF."""

    SIGNATURE = "signature"
    INITIALES = "initiales"
    DATE = "date"          # remplie automatiquement à la signature
    TEXTE = "texte"        # champ libre saisi par le signataire
    CASE = "case"          # case à cocher (consentement, option…)


class EsignDocument(Base, TimestampUpdateMixin):
    """Document PDF téléversé, à faire signer."""

    __tablename__ = "esign_documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Entreprise du groupe pour laquelle le document est signé.
    entreprise_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("entreprises.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Message personnalisé inclus dans le courriel d'invitation.
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EsignDocumentStatus.BROUILLON.value,
        server_default=EsignDocumentStatus.BROUILLON.value,
        index=True,
    )

    # Signature séquentielle : si True, les signataires reçoivent le
    # lien un à la fois, dans l'ordre `EsignSigner.order_index` — le
    # suivant n'est invité que quand le précédent a signé.
    use_signing_order: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # ----- PDF original -----
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default="application/pdf"
    )
    pdf_blob: Mapped[bytes] = deferred(
        mapped_column(LargeBinary, nullable=False)
    )
    page_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    # SHA-256 du PDF original — intégrité, repris sur la page d'audit.
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # ----- PDF final aplati (zones fusionnées + page d'audit) -----
    signed_pdf_blob: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )

    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EsignSigner(Base, TimestampUpdateMixin):
    """Signataire d'un document — banque de contacts ou création libre."""

    __tablename__ = "esign_signers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    document_id: Mapped[int] = mapped_column(
        ForeignKey("esign_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Référence facultative vers la banque de contacts unifiée
    # (`GET /contacts/all`) au format "source:id" — purement
    # informative, les coordonnées sont copiées ici.
    contact_ref: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    order_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # ----- Authentification par code SMS (optionnelle) -----
    require_sms_auth: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # On ne stocke JAMAIS le code en clair — hash SHA-256 seulement.
    sms_code_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    sms_code_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sms_code_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    sms_sent_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    sms_last_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sms_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ----- Lien public + suivi -----
    signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    open_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_ip: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    declined_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decline_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # Images PNG (encre foncée sur fond transparent) capturées sur la
    # page publique — réutilisées pour tamponner chaque zone.
    signature_image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    initials_image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )


class EsignField(Base, TimestampMixin):
    """Zone posée sur une page du PDF, assignée à un signataire.

    Coordonnées en FRACTIONS de page (0..1, origine coin haut-gauche)
    → indépendantes de la résolution d'affichage et du DPI de rendu.
    """

    __tablename__ = "esign_fields"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    document_id: Mapped[int] = mapped_column(
        ForeignKey("esign_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    signer_id: Mapped[int] = mapped_column(
        ForeignKey("esign_signers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    w: Mapped[float] = mapped_column(Float, nullable=False)
    h: Mapped[float] = mapped_column(Float, nullable=False)

    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Libellé affiché dans la zone (surtout pour kind=texte).
    label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Valeur remplie à la signature (texte saisi, date formatée,
    # "oui" pour une case cochée).
    value_text: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )


class EsignEvent(Base, TimestampMixin):
    """Journal d'audit du document (repris sur la page d'audit du PDF).

    Types : cree, envoye, relance, ouvert, sms_envoye, sms_verifie,
    signe, refuse, complete, annule.
    """

    __tablename__ = "esign_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    document_id: Mapped[int] = mapped_column(
        ForeignKey("esign_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    signer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("esign_signers.id", ondelete="SET NULL"), nullable=True
    )

    type: Mapped[str] = mapped_column(String(40), nullable=False)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
