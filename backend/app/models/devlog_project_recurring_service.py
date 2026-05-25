"""Service récurrent d'un projet Dev Logiciel.

Un projet livré peut continuer à générer des revenus mensuels via des
services récurrents (hébergement, support, abonnements, maintenance).
Ces services ne sont PAS des phases de projet : on les modélise dans
leur propre table pour découpler le suivi opérationnel (phases / tâches
finies à la livraison) du suivi commercial (MRR perpétuel).

Cycle de vie :
    * ``pending``    — créé à la signature du contrat, pas encore actif.
    * ``active``     — basculé automatiquement quand le projet passe en
                       ``status='livre'`` (event listener) OU manuellement
                       depuis l'UI.
    * ``paused``     — suspension temporaire (déjà actif, plus facturé).
    * ``cancelled``  — fin définitive (le client a résilié).

``last_invoiced_at`` est posé par le bouton « Générer la facture du mois »
(pour l'instant manuel ; cron à venir).
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


RECURRING_SERVICE_STATUSES = (
    "pending",
    "active",
    "paused",
    "cancelled",
)


class DevlogProjectRecurringService(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_project_recurring_services"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("devlog_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Libellé client (ex. « Hébergement et maintenance Pro »).
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Montant mensuel HT (cents). On reste cohérent avec
    # ``DevlogProjectPurchase.amount_cents`` (Integer en cents) pour
    # tout l'écosystème projet.
    monthly_amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Date de démarrage de la facturation récurrente. NULL tant que le
    # projet n'est pas livré (basculé à ``project.delivered_at`` par
    # l'event listener).
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )
    # Dernière facturation manuelle (bouton « Générer la facture du
    # mois »). NULL = jamais facturé.
    last_invoiced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Lien vers l'item de soumission source (optionnel — utile pour
    # remonter le coût interne / la marge appliquée à l'origine).
    source_soumission_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_soumission_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<DevlogProjectRecurringService(id={self.id}, "
            f"project_id={self.project_id}, name='{self.name}', "
            f"status='{self.status}')>"
        )
