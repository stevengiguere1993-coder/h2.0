"""Validation bancaire des loyers via QuickBooks (2026-08-14) — LECTURE
SEULE côté QBO.

Flux réel : un employé marque les loyers payés dans Kratos à la main
(1re validation). L'adjointe administrative publie les transactions
bancaires dans QuickBooks avec la convention « un compte par immeuble » :
chaque loyer encaissé est catégorisé au compte « Loyer à remettre -
{nom de l'immeuble} ». Kratos LIT ces écritures publiées et pose une
2e validation croisée (✓✓ « Validé banque ») dans le pôle locatif.

Trois tables :
- ``qbo_comptes_loyers`` — correspondance compte du plan comptable ↔
  immeuble (découverte auto + suggestion, confirmée dans Paramètres) ;
- ``qbo_transactions_loyers`` — écritures publiées importées (fenêtre
  glissante), idempotentes par (type, id QBO, compte), avec le statut de
  rapprochement déterministe (rapproché / ambigu / non rapproché) ;
- ``qbo_alias_payeurs`` — alias de payeur appris quand un humain
  confirme un rapprochement ambigu (texte normalisé → bail).

Nouvelles tables → ``ensure_validation_bancaire_tables`` (db/session.py).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QboCompteLoyer(Base):
    """Compte « Loyer à remettre - X » du plan comptable QBO, relié (ou à
    relier) à un immeuble du pôle locatif."""

    __tablename__ = "qbo_comptes_loyers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    #: Id du compte dans le plan comptable QBO (unique par compagnie —
    #: chez Phil une seule compagnie locative).
    qbo_account_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    qbo_account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Immeuble CONFIRMÉ par un humain (Paramètres). NULL = pas encore
    #: confirmé → le compte n'est pas synchronisé.
    immeuble_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    #: Suggestion automatique (similarité nom de compte ↔ nom/adresse
    #: d'immeuble) — préremplit le sélecteur, jamais appliquée seule.
    suggestion_immeuble_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    suggestion_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    derniere_synchro_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class QboTransactionLoyer(Base):
    """Écriture publiée dans QBO qui touche un compte « Loyer à
    remettre » mappé — un encaissement de loyer à rapprocher d'un bail.

    Idempotence de la synchro : (type, id QBO, compte) unique — rejouer
    la fenêtre glissante met à jour la ligne au lieu d'en créer une 2e.
    """

    __tablename__ = "qbo_transactions_loyers"
    __table_args__ = (
        UniqueConstraint(
            "qbo_txn_type", "qbo_txn_id", "qbo_account_id",
            name="uq_qbo_txn_loyer",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    #: Type d'écriture QBO (Deposit, JournalEntry, SalesReceipt…).
    qbo_txn_type: Mapped[str] = mapped_column(String(32), nullable=False)
    qbo_txn_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    qbo_account_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    compte_id: Mapped[int] = mapped_column(
        ForeignKey("qbo_comptes_loyers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    #: Immeuble dérivé du compte au moment de la synchro.
    immeuble_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    date_txn: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    montant: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    #: Payeur / mémo tel que publié (si disponible) — sert au
    #: rapprochement par texte et à l'apprentissage d'alias.
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    doc_num: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    #: "rapproche" | "ambigu" | "non_rapproche"
    statut: Mapped[str] = mapped_column(
        String(16), nullable=False, default="non_rapproche",
        server_default="non_rapproche", index=True,
    )
    bail_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_baux.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    #: 1er du mois de loyer couvert par l'encaissement (posé au
    #: rapprochement).
    mois_couvert: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    #: "auto" (rapprochement déterministe) | "manuel" (confirmé par un
    #: humain — jamais écrasé par la synchro).
    rapproche_par: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class QboAliasPayeur(Base):
    """Alias de payeur appris : « ce texte bancaire = ce bail ». Créé
    quand un humain confirme un rapprochement ambigu — le mois suivant,
    la même provenance se rapproche toute seule."""

    __tablename__ = "qbo_alias_payeurs"
    __table_args__ = (
        UniqueConstraint(
            "texte_normalise", "bail_id", name="uq_qbo_alias_payeur"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    #: Texte payeur NORMALISÉ (minuscules, sans accents, espaces
    #: aplatis) — cf. ``qbo_validation_loyers._norm``.
    texte_normalise: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    bail_id: Mapped[int] = mapped_column(
        ForeignKey("imm_baux.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
