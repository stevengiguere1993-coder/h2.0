"""Report d'un petit solde impayé sur une prochaine facture du même client.

Steven (2026-11-02) : « parfois les clients reçoivent de très gros montants
et de petits montants sont oubliés (15 $ sur une facture de 18 000 $) ».
Le solde est FERMÉ sur la facture d'origine (dans QuickBooks : un Payment
déposé dans le compte de transit « Soldes reportés ») et AJOUTÉ, hors
taxes, sur la prochaine facture du client (ligne ``kind="report"`` dont
le produit QB pointe sur le même compte de transit). Le compte de transit
revient à 0 ; revenus et taxes ne bougent pas.

Un report n'est PAS un paiement : il ne compte ni dans les entrées de
fonds, ni dans les finances de projet, ni dans le profit. La facture
d'origine est soldée par « paiements + reports ».

Statuts :
- ``en_attente`` : solde fermé sur l'origine, pas encore sur une facture ;
- ``applique``   : ligne ajoutée sur la facture cible ;
- ``annule``     : report annulé (la facture d'origine redevient ouverte).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


REPORT_EN_ATTENTE = "en_attente"
REPORT_APPLIQUE = "applique"
REPORT_ANNULE = "annule"


class FactureReportSolde(Base, TimestampUpdateMixin):
    __tablename__ = "facture_reports_solde"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Facture dont le petit solde est fermé.
    origine_facture_id: Mapped[int] = mapped_column(
        ForeignKey("factures.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Facture qui porte la ligne « Solde reporté de la facture X ».
    cible_facture_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("factures.id", ondelete="SET NULL"), nullable=True, index=True
    )
    cible_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("facture_items.id", ondelete="SET NULL"), nullable=True
    )
    #: Facture d'où la ligne a été retirée à la main : le report ne s'y
    #: ré-applique pas (il attend la facture suivante).
    facture_exclue_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    #: Montant TTC reporté (les taxes ont été facturées sur l'origine).
    montant: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    statut: Mapped[str] = mapped_column(
        String(16), nullable=False, default=REPORT_EN_ATTENTE, index=True
    )
    #: Report déclenché en classant la facture « payée » (vs bouton).
    automatique: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    #: Payment QB qui ferme le solde de l'Invoice d'origine (déposé dans le
    #: compte de transit « Soldes reportés »).
    qbo_payment_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    #: Dernier refus de QuickBooks (le filet horaire réessaie).
    qbo_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    annule_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
