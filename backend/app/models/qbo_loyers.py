"""Validation bancaire des loyers via QuickBooks (2026-08-14) — LECTURE
SEULE côté QBO.

Flux réel : un employé marque les loyers payés dans Kratos à la main
(1re validation). L'adjointe administrative publie les transactions
bancaires dans QuickBooks avec la convention « un compte par immeuble » :
chaque loyer encaissé est catégorisé au compte « Loyer à remettre -
{nom de l'immeuble} ». Kratos LIT ces écritures publiées et pose une
2e validation croisée (✓✓ « Validé banque ») dans le pôle locatif.

Quatre tables :
- ``qbo_comptes_loyers`` — compte du plan comptable découvert (suggestion
  auto, confirmé dans Paramètres). Un compte peut couvrir PLUSIEURS
  immeubles (« 9085 Millen & 710 Legendre ») via ``qbo_compte_immeubles``,
  ou TOUS les immeubles internes (compte fiducie qui reçoit les virements
  Interac de tous les locataires) via ``tous_les_immeubles`` ;
- ``qbo_compte_immeubles`` — lien N-N compte ↔ immeubles (retour Phil
  2026-08-14 : le lien 1-1 ``immeuble_id`` ne collait pas au terrain) ;
- ``qbo_transactions_loyers`` — écritures publiées importées (fenêtre
  glissante), idempotentes par (type, id QBO, compte), avec le statut de
  rapprochement déterministe (rapproché / ambigu / non rapproché) et les
  SORTIES d'argent conservées à titre informatif (statut « ignoree »,
  jamais candidates au rapprochement) ;
- ``qbo_alias_payeurs`` — alias de payeur appris quand un humain
  confirme un rapprochement ambigu (texte normalisé → bail).

Nouvelles tables → ``ensure_validation_bancaire_tables`` (db/session.py) ;
nouvelles COLONNES → aussi ``ensure_critical_columns`` (piège migration :
les tables préexistantes ne reçoivent rien de create_all).
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
    relier) à un ou PLUSIEURS immeubles du pôle locatif — ou à tous."""

    __tablename__ = "qbo_comptes_loyers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    #: Id du compte dans le plan comptable QBO (unique par compagnie —
    #: chez Phil une seule compagnie locative).
    qbo_account_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    qbo_account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: LEGACY (lien 1-1 d'origine). Migré au boot vers
    #: ``qbo_compte_immeubles`` puis remis à NULL — ne plus s'en servir.
    immeuble_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    #: Compte « fourre-tout » (fiducie) : couvre TOUS les immeubles
    #: internes — la sélection fine de ``qbo_compte_immeubles`` est
    #: alors ignorée. Colonne additive → ensure_critical_columns.
    tous_les_immeubles: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    #: Suggestion automatique (similarité nom de compte ↔ nom/adresse
    #: d'immeuble) — préremplit le sélecteur, jamais appliquée seule.
    #: LEGACY : meilleure suggestion unique (gardée pour compat) ; la
    #: liste complète vit dans ``suggestion_immeubles_json``.
    suggestion_immeuble_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    #: JSON ``[immeuble_id, …]`` — TOUTES les suggestions (un nom de
    #: compte « 9085 Millen & 710 Legendre » suggère les deux).
    #: Colonne additive → ensure_critical_columns.
    suggestion_immeubles_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    #: Nom générique (fiducie/fonds) → on suggère la case « tous les
    #: immeubles » au lieu d'un immeuble précis. Colonne additive →
    #: ensure_critical_columns.
    suggestion_tous: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
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


class QboCompteImmeuble(Base):
    """Lien N-N compte « Loyer à remettre » ↔ immeuble (un compte QBO
    peut couvrir plusieurs immeubles Kratos — retour Phil 2026-08-14).
    Les liens sont CONFIRMÉS par un humain dans Paramètres ; le boot
    recopie les anciens ``immeuble_id`` 1-1 ici (rien n'est perdu)."""

    __tablename__ = "qbo_compte_immeubles"
    __table_args__ = (
        UniqueConstraint(
            "compte_id", "immeuble_id", name="uq_qbo_compte_immeuble"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    compte_id: Mapped[int] = mapped_column(
        ForeignKey("qbo_comptes_loyers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        nullable=False, index=True,
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
    #: Immeuble de la transaction : celui du bail une fois rapprochée ;
    #: sinon celui du compte quand il n'en couvre qu'un seul ; NULL pour
    #: un compte multi-immeubles/fiducie tant que rien n'est rapproché.
    immeuble_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    date_txn: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: Toujours en VALEUR ABSOLUE — le sens (entrée/sortie) est classé
    #: par TYPE d'écriture, pas par signe (sur un compte de passif, un
    #: dépôt est un crédit et le signe dépend de la représentation).
    montant: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    #: "entree" (dépôt de loyer, candidate au rapprochement) | "sortie"
    #: (virement de remise, dépense… conservée pour info seulement).
    #: Colonne additive → ensure_critical_columns.
    sens: Mapped[str] = mapped_column(
        String(8), nullable=False, default="entree",
        server_default="entree",
    )
    #: Payeur / mémo tel que publié (si disponible) — sert au
    #: rapprochement par texte et à l'apprentissage d'alias.
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Payeur EXTRAIT du mémo bancaire (« Virement Interac de /DRISSA
    #: KONE / » → « DRISSA KONE ») — affiché dans le fil et prioritaire
    #: pour le rapprochement par texte. Colonne additive →
    #: ensure_critical_columns.
    payeur: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    doc_num: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    #: "rapproche" | "ambigu" | "non_rapproche" | "ignoree" (sortie
    #: d'argent — jamais candidate au rapprochement, gardée pour le fil)
    statut: Mapped[str] = mapped_column(
        String(16), nullable=False, default="non_rapproche",
        server_default="non_rapproche", index=True,
    )
    #: Pourquoi la ligne est ignorée (statut « ignoree ») — ex.
    #: "sortie_argent". Colonne additive → ensure_critical_columns.
    ignore_raison: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    bail_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_baux.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    #: 1er du mois de loyer couvert par l'encaissement (posé au
    #: rapprochement). Pour un paiement MULTI-MOIS (2 mois de retard
    #: payés d'un coup), c'est le PREMIER mois couvert.
    mois_couvert: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    #: DERNIER mois couvert quand l'encaissement règle plusieurs mois
    #: consécutifs (NULL = un seul mois). Colonne additive →
    #: ensure_critical_columns.
    mois_couvert_fin: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
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
