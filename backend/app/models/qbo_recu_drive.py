"""Reçus QuickBooks copiés dans Google Drive — journal / mémoire.

Chantier Phil 2026-10-04 : chaque reçu (pièce jointe image ou PDF
d'une dépense QuickBooks) de chaque compagnie est copié dans le Drive
de l'entreprise, sous Factures / <année> / <Mois>, nommé
« AAAA-MM-JJ Fournisseur 2134,02$.pdf ».

Une ligne par (compagnie, pièce jointe, transaction liée). C'est la
mémoire anti-doublon : une pièce jointe déjà traitée n'est jamais
recopiée, même si le fichier a été supprimé du Drive à la main.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QboRecuDrive(Base):
    __tablename__ = "qbo_recus_drive"
    __table_args__ = (
        UniqueConstraint(
            "realm_id", "attachable_id", "txn_type", "txn_id",
            name="uq_qbo_recus_drive_piece",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entreprise_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("entreprises.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: Compagnie QuickBooks (realmId) — la clé stable même si le lien
    #: Kratos ↔ entreprise change.
    realm_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attachable_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: « Purchase » (dépense / chèque / carte), « Bill » (facture
    #: fournisseur) ou « » (pièce jointe sans transaction → classée dans le
    #: mois de son dépôt ; « Non classé » seulement sans aucune date).
    txn_type: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    txn_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    date_recu: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    fournisseur: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    montant: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    nom_fichier: Mapped[str] = mapped_column(String(255), nullable=False)

    drive_folder_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    drive_file_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    #: « copie » (téléversé), « ignore_doublon » (un fichier du même nom
    #: existait déjà dans le dossier du mois), « rattache » (reçu brut dont
    #: le fichier a été renommé avec sa dépense : la ligne de la dépense
    #: porte désormais ce fichier), « erreur ».
    statut: Mapped[str] = mapped_column(String(24), nullable=False, default="copie")
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: « rattrapage » (bouton), « cron » (nuit).
    declencheur: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    #: Identifiant du run (pour « Annuler cet import » : corbeille Drive +
    #: oubli de la mémoire). Colonne additive (ajoutée au démarrage).
    run_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
