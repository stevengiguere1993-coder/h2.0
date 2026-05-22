"""Soumission (devis) du pôle Développement logiciel.

Un devis envoyé à un lead ou à un client. Le pipeline du closer a une
étape « soumission » : c'est ici qu'on suit le devis correspondant.

Refonte 2026-05 : nouveau format de devis (« devis_dev ») avec deux
sections — frais mensuels récurrents et frais de mise en oeuvre — et
un calcul de marge circulaire (la commission du closer absorbe la
marge sur la base, ce qui force la résolution algébrique fermée
décrite dans ``app.services.devlog_devis_calc``). Les soumissions
créées avant la refonte gardent ``is_devis_dev = False`` et restent
disponibles en lecture seule.

Extension 2026-05 (vague 1) : pipeline d'envoi PDF + signature
publique — ``signature_token`` opaque + ``sent_at`` /
``signed_at`` / ``signed_name`` / ``signed_ip`` pour l'audit trail
(pattern aligné sur Offer / DevlogContract).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin

#: Statuts d'une soumission — alignés sur le pôle Construction
#: (5 colonnes du kanban : brouillon → envoyée → acceptée / refusée / expirée).
SOUMISSION_STATUSES = (
    "brouillon",
    "envoyee",
    "acceptee",
    "refusee",
    "expiree",
)


class DevlogSoumission(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_soumissions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    # Une soumission cible un lead (prospect) et/ou un client.
    lead_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="brouillon",
        server_default="brouillon", index=True,
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Refonte « devis_dev » (mai 2026) -------------------------------
    # Flag : True = nouveau format (section mensuelle + section mise en
    # oeuvre avec calcul circulaire). False = ancien format générique
    # (sections + items), conservé en lecture seule pour l'historique.
    is_devis_dev: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    # Pourcentages — stockés en valeurs « humaines » (50 = 50 %).
    marge_recurrente_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    marge_initiale_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    commission_closer_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    # Taux horaires utilisés pour transformer les heures en coût avant
    # marge. Toujours appliqués à la mise en oeuvre (jamais au mensuel).
    taux_dev_horaire: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    taux_manager_horaire: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    heures_manager: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 2), nullable=True
    )

    # Texte libre affiché à la place de la liste de coûts mensuels dans
    # la vue client (« Hébergement + maintenance + 24/7 », etc.).
    client_recurring_description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # --- Envoi PDF + signature publique (vague 1, mai 2026) ------------
    # Token opaque (32 octets URL-safe) qui sert d'authentification
    # pour la page publique /devlog/sign-soumission/{token}.
    signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    # Horodatage envoi / signature — utilisés par l'UI (badges et
    # historique) et par l'audit interne.
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

    def __repr__(self) -> str:
        return f"<DevlogSoumission(id={self.id}, title='{self.title}', status='{self.status}')>"
