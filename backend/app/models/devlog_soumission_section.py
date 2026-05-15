"""Section d'une soumission Dev logiciel.

Une soumission est structurée en sections (un pôle de dev = une section :
Frontend, Backend, Design, DevOps, etc.). Chaque section a son propre
markup et son mode de facturation :

  * `initial`   — frais payés à la livraison (développement, design…)
  * `recurring` — frais mensuels (hosting + softwares + maintenance,
                  obligatoires car Horizon héberge le produit du client)

Le markup_percent est interne (jamais visible côté client). Le client
ne voit que les prix finaux (qty × cost × (1 + markup/100)).
"""

from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


SECTION_BILLING_KINDS = ("initial", "recurring")


class DevlogSoumissionSection(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_soumission_sections"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    soumission_id: Mapped[int] = mapped_column(
        ForeignKey("devlog_soumissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Nom du pôle (Frontend, Backend, Design, DevOps, Hosting, …).
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # initial | recurring (mensuel)
    billing_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="initial",
        server_default="initial", index=True,
    )
    # Pourcentage de majoration appliqué au coût pour obtenir le prix
    # client. NULL ou 0 → pas de markup (rare). Ex. 100 = double.
    markup_percent: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    # Étiquette client (ce que voit le client sur le PDF). Si NULL,
    # on affiche `name` côté client aussi. Ex. interne « Hosting »,
    # côté client « Hébergement et abonnements logiciels ».
    client_label: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<DevlogSoumissionSection(id={self.id}, "
            f"name='{self.name}', kind='{self.billing_kind}')>"
        )
