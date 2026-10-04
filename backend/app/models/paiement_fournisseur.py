"""Paiements fournisseurs par dépôt direct Desjardins (Comptabilité).

Demande Steven (2026-10-04) : une technicienne comptable prépare les
paiements des factures fournisseurs sans jamais pouvoir faire sortir
l'argent elle-même. Kratos reproduit ce que fait Plooto :

- la technicienne choisit les factures à payer (lues dans le QuickBooks
  de l'entreprise) et forme un LOT ;
- un approbateur (capacité ``paiements.approuver`` + double
  authentification) l'approuve, jamais la personne qui l'a préparé ;
- Kratos crée le fichier de dépôt direct (norme 005 de Paiements
  Canada) que l'approbateur transmet lui-même dans AccèsD Affaires ;
- les paiements sont ensuite inscrits dans QuickBooks.

Les coordonnées bancaires des fournisseurs sont chiffrées et n'entrent
en usage qu'une fois approuvées par une autre personne que celle qui les
a saisies. Une ligne de compte n'est jamais modifiée : un changement crée
une nouvelle ligne, l'ancienne passe à « remplace ».
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaiementReglage(Base):
    """Réglages du dépôt direct d'une entreprise (son entente Desjardins)."""

    __tablename__ = "paiements_reglages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    #: Numéro d'organisme de 10 caractères remis par la caisse.
    numero_organisme: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    #: Centre de traitement de destination (Desjardins : 81510).
    centre_traitement: Mapped[str] = mapped_column(
        String(5), nullable=False, default="81510"
    )
    #: Code de transaction de la norme 007 (460 = comptes fournisseurs).
    code_transaction: Mapped[str] = mapped_column(
        String(3), nullable=False, default="460"
    )
    nom_court: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    nom_long: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    #: Compte de l'entreprise où reviennent les dépôts refusés.
    retour_institution: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    retour_transit: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    retour_compte: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    #: Nombre d'approbateurs distincts exigés pour un lot (1 ou 2).
    approbations_requises: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    #: Numéro du prochain fichier (0001 à 9999, puis retour à 0001).
    prochain_numero_fichier: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    #: Compte bancaire QuickBooks d'où partent les paiements inscrits.
    qbo_compte_banque_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    qbo_compte_banque_nom: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    modifie_par_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )


class FournisseurCompteBancaire(Base):
    """Coordonnées bancaires d'un fournisseur QuickBooks, pour une entreprise."""

    __tablename__ = "paiements_comptes_fournisseurs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    qbo_vendor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    fournisseur_nom: Mapped[str] = mapped_column(String(255), nullable=False)
    institution: Mapped[str] = mapped_column(String(3), nullable=False)
    transit: Mapped[str] = mapped_column(String(5), nullable=False)
    #: Numéro de compte chiffré (``secret_vault``) ; jamais renvoyé en clair
    #: par l'API, sauf dans le fichier de dépôt créé par un approbateur.
    compte_chiffre: Mapped[str] = mapped_column(Text, nullable=False)
    #: Quatre derniers chiffres, pour l'affichage.
    compte_fin: Mapped[str] = mapped_column(String(4), nullable=False)
    #: D'où viennent les coordonnées (ex. « spécimen de chèque reçu le 3 oct. »).
    source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    #: « en_attente », « approuve », « remplace », « refuse » ou « retire ».
    statut: Mapped[str] = mapped_column(
        String(16), nullable=False, default="en_attente", index=True
    )
    propose_par_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    propose_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decide_par_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decide_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    motif: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class LotPaiement(Base):
    """Un lot de paiements fournisseurs = un fichier de dépôt direct."""

    __tablename__ = "paiements_lots"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: « brouillon », « soumis », « approuve », « fichier_cree »,
    #: « transmis », « paye », « refuse » ou « annule ».
    statut: Mapped[str] = mapped_column(
        String(16), nullable=False, default="brouillon", index=True
    )
    #: Date où l'argent arrive chez les fournisseurs.
    date_paiement: Mapped[date] = mapped_column(Date, nullable=False)
    total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    nb_lignes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Copie du réglage au moment de la soumission.
    approbations_requises: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    cree_par_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    soumis_par_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    soumis_le: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approuve_le: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Fichier de dépôt : numéro, date de création inscrite dans le
    #: fichier et empreinte, pour le recréer à l'identique.
    fichier_numero: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fichier_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    fichier_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fichier_cree_par_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    fichier_cree_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    transmis_par_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    transmis_le: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Paiements inscrits dans QuickBooks.
    paye_le: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    annule_par_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    annule_le: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    motif_annulation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )


class LotPaiementLigne(Base):
    """Une facture QuickBooks payée (en tout ou en partie) par un lot."""

    __tablename__ = "paiements_lots_lignes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    lot_id: Mapped[int] = mapped_column(
        ForeignKey("paiements_lots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    qbo_bill_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    qbo_vendor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fournisseur_nom: Mapped[str] = mapped_column(String(255), nullable=False)
    numero_facture: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    date_facture: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    echeance: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    #: Solde de la facture dans QuickBooks quand elle a été ajoutée.
    solde_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    montant_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: Compte bancaire approuvé figé à la soumission du lot.
    compte_bancaire_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("paiements_comptes_fournisseurs.id", ondelete="SET NULL"),
        nullable=True,
    )
    qbo_bill_payment_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    erreur_qbo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class LotPaiementApprobation(Base):
    """Décision d'un approbateur sur un lot (une seule par personne)."""

    __tablename__ = "paiements_lots_approbations"
    __table_args__ = (
        UniqueConstraint("lot_id", "user_id", name="uq_paiements_lot_approbateur"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    lot_id: Mapped[int] = mapped_column(
        ForeignKey("paiements_lots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: « approuve » ou « refuse ».
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    commentaire: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PaiementEvenement(Base):
    """Journal des paiements : chaque geste, qui et quand. Jamais modifié."""

    __tablename__ = "paiements_journal"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("entreprises.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lot_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("paiements_lots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    compte_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("paiements_comptes_fournisseurs.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Utilisateur2FA(Base):
    """Double authentification (application d'authentification, TOTP)."""

    __tablename__ = "utilisateurs_2fa"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    #: Clé secrète chiffrée (``secret_vault``).
    secret_chiffre: Mapped[str] = mapped_column(Text, nullable=False)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_le: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Dernier pas de 30 s accepté : un code ne sert qu'une fois.
    dernier_pas: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    #: Après un code valide, les gestes sensibles passent sans nouveau
    #: code jusqu'à cette heure (5 minutes).
    confirme_jusqu_a: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )
