"""FactureItem — line item attached to a Facture (client invoice)."""

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class FactureItem(Base, TimestampUpdateMixin):
    __tablename__ = "facture_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    facture_id: Mapped[int] = mapped_column(
        ForeignKey("factures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Texte long autorisé (listes multi-lignes saisies dans l'éditeur).
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # 6 décimales : la facturation progressive porte l'avancement sur la
    # quantité (prix unitaire du devis conservé) — 3 décimales faisaient
    # dériver les gros prix unitaires de plusieurs dollars.
    quantity: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    # Catégorie de ligne (introduit pour tracker les extras hors
    # soumission — ex. main-d'œuvre supplémentaire, ajout en cours de
    # chantier). « service » = ligne standard chargée sur le contrat.
    # « materiaux » = matériel / fournitures (achats refacturés), traité
    # comme un service dans les calculs. « extra » = ligne hors-contrat,
    # ne réduit pas le « reste à facturer » de la soumission et bonifie
    # le profit réel quand encaissée. « rabais » = ligne négative.
    # « frais » = ligne sans taxes (ex. frais de déplacement absorbés).
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="service", index=True
    )

    # Ligne HORS SOUMISSION DE BASE sans être un « extra » : la
    # main-d'œuvre et les achats IMPORTÉS sur un projet qui a une
    # soumission gardent leur vrai type (Service / Matériaux) mais ne
    # comptent pas dans l'avancement du devis — même effet comptable
    # qu'« extra » (retour Steven 2026-10-14 : « il s'agit de services et
    # de matériaux, non pas d'extra »). Toujours lire via
    # app.services.facture_lignes.est_hors_soumission.
    hors_soumission: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Item de la SOUMISSION d'origine (facturation progressive) : permet
    # de suivre, item par item, combien a déjà été chargé au client — un
    # item facturé au complet ne réapparaît plus sur les factures à
    # pourcentage suivantes. NULL pour les lignes manuelles / acomptes /
    # extras.
    soumission_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("soumission_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
