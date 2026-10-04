"""Reçus saisis dans Kratos et envoyés à QuickBooks — trace minimale.

Formulaire « Reçus » du pôle Entreprises (Steven 2026-10-04) : on choisit
l'inc, on remplit les mêmes champs que l'écran Dépense / Facture
fournisseur de QuickBooks, et Kratos crée la transaction directement dans
le QuickBooks de l'inc, photo du reçu en pièce jointe. Le reçu lui-même
n'est PAS gardé dans Kratos : la copie de nuit (``qbo_recus_drive``) le
récupère dans QuickBooks et le range dans le Drive.

Cette table ne garde que qui a envoyé quoi et quand (inc, numéro de la
transaction QuickBooks), plus la clé d'envoi du formulaire qui bloque un
double envoi (double-clic, réseau lent). Ni montant, ni fournisseur, ni
fichier : QuickBooks reste la seule source.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecuQboSaisi(Base):
    __tablename__ = "recus_qbo_saisis"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    #: Clé générée par le formulaire, une par reçu : un deuxième envoi
    #: avec la même clé renvoie le résultat du premier au lieu de créer
    #: une deuxième dépense dans QuickBooks.
    cle_envoi: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    entreprise_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("entreprises.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: Connexion QuickBooks utilisée : « inc:{id} » ou « construction ».
    qbo_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    realm_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    #: « Purchase » (Dépense, payée) ou « Bill » (Facture à payer).
    txn_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    txn_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    #: « en_cours » (envoi en train de se faire), « envoye » (transaction
    #: créée, photo jointe), « photo_a_reprendre » (transaction créée mais
    #: la photo n'a pas pu être jointe : on peut la renvoyer seule).
    statut: Mapped[str] = mapped_column(
        String(24), nullable=False, default="en_cours"
    )
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
