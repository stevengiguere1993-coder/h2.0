"""Portail Investisseur v2 — participation par COMPAGNIE.

Modèle d'affaires (brainstorm 2026-08-13) : un investisseur met du
capital dans une compagnie (INC) au jour 1 et obtient un % des parts ;
la compagnie achète un ou des immeubles ; phase d'optimisation (~0-2
ans), refinancement, remboursement du capital ; l'investisseur reste
actionnaire à long terme. Pas d'intérêt — le rendement est interne
(équité + remboursements), mesuré par un vrai TRI (XIRR) sur les flux
datés réels.

Le pôle est en LECTURE SEULE côté investisseur : tout est assemblé
depuis le pôle locatif (loyers, paiements, dépenses, hypothèques,
évaluations) via la chaîne existante entreprise → immeubles
(`Immeuble.owner_entreprise_id` / `ImmeubleOwnership`). Seuls le
capital, les remboursements, les jalons et les documents partagés sont
saisis ici (une fois).

L'ancien modèle v0 (`Investissement`/`Distribution`, lié à UN immeuble)
reste en place mais n'est plus la source du portail.

Tables créées par `ensure_invest_portal_tables()` (app/db/session.py).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampMixin, TimestampUpdateMixin


class InvestFluxType(str, Enum):
    """Types de flux entre l'investisseur et la compagnie.

    - apport        : argent injecté par l'investisseur (sortie de SA poche)
    - remboursement : remboursement de capital (refinancement, typiquement)
    - dividende     : distribution de profits
    - sortie        : rachat/vente des parts (fin de participation)
    """

    APPORT = "apport"
    REMBOURSEMENT = "remboursement"
    DIVIDENDE = "dividende"
    SORTIE = "sortie"


class InvestParticipation(Base, TimestampUpdateMixin):
    """Parts d'un investisseur (User, volet investisseur) dans une
    compagnie du groupe."""

    __tablename__ = "inv_participations"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "entreprise_id", name="uq_inv_participation"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    parts_pct: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)

    #: actif | sorti (sortie = rachat des parts, participation close)
    statut: Mapped[str] = mapped_column(
        String(16), nullable=False, default="actif", server_default="actif"
    )
    #: Interrupteur de publication : False = l'investisseur ne voit pas
    #: (encore) ce projet dans son portail.
    is_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class InvestFlux(Base, TimestampMixin):
    """Flux daté entre l'investisseur et la compagnie — nourrit le TRI."""

    __tablename__ = "inv_flux"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    participation_id: Mapped[int] = mapped_column(
        ForeignKey("inv_participations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    type: Mapped[str] = mapped_column(String(16), nullable=False)
    montant: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    date_flux: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    #: manuel | qbo (enrichissement futur : flux proposés depuis QBO)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manuel", server_default="manuel"
    )


class InvestProjetProfil(Base, TimestampUpdateMixin):
    """Réglages de publication d'un projet (1 ligne par entreprise).

    Créé à la volée avec des défauts sensés — l'admin n'a RIEN à
    configurer pour publier un projet.
    """

    __tablename__ = "inv_projet_profils"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    #: Petit texte de présentation affiché en tête de la fiche projet.
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    #: Phase affichée : NULL = déduite automatiquement (projet
    #: d'optimisation actif → « optimisation », sinon « long_terme »).
    phase_override: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )

    #: Avances aux actionnaires (dette de la compagnie envers eux) —
    #: soustraites de l'équité : équité = valeur − hypothèques −
    #: avances. Saisie manuelle pour l'instant (candidate à un tirage
    #: QBO auto via le mapping de la section optimisation).
    avances_actionnaires: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    #: Dernière synchronisation QuickBooks (avances d'actionnaires) :
    #: horodatage + résumé JSON {statut, projet_nom, avances_total,
    #: apparies, sans_compte, non_apparies, erreur?} — affiché dans la
    #: console pour que l'état de la sync soit toujours visible.
    #: Colonnes additives.
    qbo_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    qbo_sync_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # ── Interrupteurs de transparence (défauts = transparent) ──
    show_depenses: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    show_hypotheque: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    show_actionnaires: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    show_cashflow: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    #: Budget du projet d'optimisation (enveloppes, dépensé réel,
    #: reste) — « où est-ce que leur argent a été dépensé » (Phil,
    #: 2026-08-25). Colonne additive.
    show_budget: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class InvestDocument(Base, TimestampMixin):
    """Document partagé aux investisseurs d'une compagnie.

    Deux sources : téléversement direct, ou fichier COCHÉ dans le Drive
    (dont on stocke une copie au moment du partage — l'investisseur ne
    touche jamais au Drive lui-même).
    """

    __tablename__ = "inv_documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    #: upload | drive
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="upload", server_default="upload"
    )
    drive_file_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    content_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default="application/pdf"
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    blob: Mapped[bytes] = deferred(
        mapped_column(LargeBinary, nullable=False)
    )


class InvestJalon(Base, TimestampMixin):
    """Jalon manuel de la timeline d'un projet (en plus des événements
    déduits automatiquement : acquisitions, flux, phase)."""

    __tablename__ = "inv_jalons"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    date_jalon: Mapped[date] = mapped_column(Date, nullable=False)
    titre: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: acquisition | optimisation | refinancement | autre — pilote la
    #: pastille de couleur dans la timeline.
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="autre", server_default="autre"
    )
