"""Dossiers de FINANCEMENT d'un immeuble (Gestion locative → Financement,
Phil 2026-10-16) : « je veux que mes financements deviennent faciles ».

Un dossier = une demande à un prêteur (refinancement, achat,
renouvellement) pour UN immeuble : qui, combien, où on en est, les pièces
à fournir (checklist cochable, chaque pièce pointant vers un document du
dossier), le journal des échanges et une projection pro forma par unité
(toujours identifiée comme projection — jamais mélangée aux baux).

Garde-fou de conception : tout montant qui sort d'ici (rent roll, paquet
PDF) vient d'un bail ENREGISTRÉ (``imm_baux``) ou d'une colonne marquée
« projection ». Il n'existe aucun champ « montant pour la banque ».

Tables créées par ``create_all`` au démarrage (filet
``ensure_critical_columns``).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, TimestampUpdateMixin

FINANCEMENT_TYPES: tuple[str, ...] = ("refinancement", "achat", "renouvellement", "autre")
FINANCEMENT_STATUTS: tuple[str, ...] = (
    "preparation",   # on monte le dossier
    "envoye",        # transmis au prêteur / courtier
    "en_analyse",    # questions, pièces complémentaires
    "approuve",
    "refuse",
    "clos",          # terminé (déboursé, abandonné…)
)
STATUTS_OUVERTS: tuple[str, ...] = ("preparation", "envoye", "en_analyse")
PIECE_TYPES: tuple[str, ...] = (
    "rent_roll", "baux", "baux_paralleles", "avis", "etats_financiers",
    "releve_hypothecaire", "taxes", "assurance", "evaluation", "offre_achat",
    "identite", "organigramme", "autre",
)
JOURNAL_TYPES: tuple[str, ...] = ("note", "envoi", "appel", "courriel", "reponse", "statut")


class Financement(Base, TimestampUpdateMixin):
    __tablename__ = "imm_financements"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Hypothèque existante refinancée / renouvelée (facultatif).
    hypotheque_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_hypotheques.id", ondelete="SET NULL"), nullable=True
    )
    titre: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="refinancement", server_default="refinancement"
    )
    preteur: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    courtier: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    montant_demande: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    taux_pct: Mapped[Optional[float]] = mapped_column(Numeric(6, 3), nullable=True)
    terme_mois: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    amortissement_mois: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    statut: Mapped[str] = mapped_column(
        String(16), nullable=False, default="preparation", server_default="preparation", index=True
    )
    date_depot: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_reponse: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    #: Échéance à respecter (renouvellement du terme, date de clôture…).
    date_echeance: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    #: Catégories de baux dans le rent roll du dossier (les deux par défaut).
    inclure_standards: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    inclure_paralleles: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    #: Projection pro forma : {"logements": {"<id>": {"loyer": 1450,
    #: "source": "manuel|demande|marche", "note": ""}}, "hypotheses":
    #: {"vacance_pct": 3}}. Toujours affichée comme PROJECTION.
    projection_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


class FinancementPiece(Base, TimestampUpdateMixin):
    """Pièce de la checklist d'un dossier : à fournir / fournie (document
    du dossier) / envoyée (date)."""

    __tablename__ = "imm_financement_pieces"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    financement_id: Mapped[int] = mapped_column(
        ForeignKey("imm_financements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="autre", server_default="autre")
    libelle: Mapped[str] = mapped_column(String(255), nullable=False)
    requis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    #: Document du dossier (imm_documents) qui remplit la pièce.
    document_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    #: Pièce PRODUITE par Kratos à la demande (rent roll, paquet) : pas de
    #: document stocké, cochée quand elle a été envoyée.
    envoye_le: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class FinancementJournal(Base, TimestampMixin):
    """Journal des échanges (note, envoi, appel, courriel, réponse,
    changement de statut) — le « suivi dans le temps »."""

    __tablename__ = "imm_financement_journal"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    financement_id: Mapped[int] = mapped_column(
        ForeignKey("imm_financements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="note", server_default="note")
    texte: Mapped[str] = mapped_column(Text, nullable=False)
    auteur_email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


__all__ = [
    "Financement",
    "FinancementPiece",
    "FinancementJournal",
    "FINANCEMENT_TYPES",
    "FINANCEMENT_STATUTS",
    "STATUTS_OUVERTS",
    "PIECE_TYPES",
    "JOURNAL_TYPES",
]
