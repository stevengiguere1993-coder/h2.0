"""Liste d'achats de MATÉRIAUX d'un projet (étape 3 du catalogue,
2026-09-25).

Une ligne = un matériau du catalogue à acheter pour un chantier,
rattachée (optionnellement) à une phase de planification et à un
magasin choisi. Le prix prévu est un instantané du meilleur prix connu
au moment de l'ajout ; le prix courant est recalculé à la lecture depuis
les offres du catalogue (relevé automatique quotidien), ce qui permet :

- de voir l'économie possible si un magasin passe en rabais ;
- d'alerter les gestionnaires (cloche + push) quand un article encore à
  acheter est en rabais (``services/materiaux_alertes.py``) ;
- de comparer le prévu / l'acheté au budget de la phase et au coûtant
  matériaux de la soumission ;
- de générer un bon de commande (PO) par magasin à partir des lignes.

Nouvelle table → create_all au démarrage ; colonnes nullables ou à défaut.
Déclarée dans api_ia_couverture (cliquet « IA au courant »).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ProjetMateriau(Base):
    __tablename__ = "projet_materiaux"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phase_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("project_phases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    materiau_id: Mapped[int] = mapped_column(
        ForeignKey("materiaux.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[float] = mapped_column(
        Numeric(12, 3), nullable=False, default=1, server_default="1"
    )
    #: Unité de la ligne (copie de celle du matériau, modifiable).
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    #: Magasin CHOISI pour l'achat (NULL = au meilleur prix du moment).
    magasin_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("magasins.id", ondelete="SET NULL"), nullable=True
    )
    #: Prix unitaire PRÉVU (instantané au moment de l'ajout ou du choix
    #: du magasin) — base du budget de la liste.
    prix_prevu: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    #: a_acheter | achete
    statut: Mapped[str] = mapped_column(
        String(16), nullable=False, default="a_acheter", server_default="a_acheter", index=True
    )
    #: Prix unitaire réellement payé et date d'achat (statut « achete »).
    prix_paye: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    achete_le: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    #: Liens vers le PO généré et/ou l'achat réel (comptable).
    purchase_order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True
    )
    achat_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("achats.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: Clé du dernier rabais signalé pour cette ligne
    #: (« magasin:prix:fin ») — évite de notifier deux fois le même rabais.
    derniere_alerte_cle: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    materiau: Mapped["Materiau"] = relationship()  # noqa: F821
    magasin: Mapped[Optional["Magasin"]] = relationship()  # noqa: F821
