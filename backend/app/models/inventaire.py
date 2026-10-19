"""Inventaire INTERNE de l'entreprise (Steven 2026-10-18).

« Une section avec notre inventaire qu'on utilise sur un projet et qu'on
va recharger de notre inventaire interne » — onglet « Inventaire » du
catalogue de services.

- ``InventaireArticle``   : un article en stock (nom, catégorie, unité),
                            la quantité en main et son coût unitaire
                            MOYEN hors taxes (moyenne pondérée des
                            entrées).
- ``InventaireMouvement`` : chaque entrée, ajustement de compte ou sortie
                            vers un projet. Une SORTIE crée sur le projet
                            un achat de nature « inventaire »
                            (``Achat.kind = KIND_INVENTAIRE``) : coût du
                            projet, refacturable comme le matériel (ligne
                            « Matériaux » de la facture), jamais poussé
                            dans QuickBooks — voir services/inventaire.py.

Nouvelles tables → create_all au démarrage. Déclarées dans
api_ia_couverture (cliquet « IA au courant »).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InventaireArticle(Base):
    __tablename__ = "inventaire_articles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    #: Catégorie libre : Électricité, Plomberie, Quincaillerie, Gypse…
    categorie: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    #: Unité de compte : unité, boîte, rouleau, pi, sac…
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    #: Quantité EN MAIN — tenue par les mouvements (entrée, ajustement,
    #: sortie), jamais modifiée directement.
    quantite: Mapped[float] = mapped_column(
        Numeric(12, 3), nullable=False, default=0, server_default="0"
    )
    #: Coût unitaire MOYEN hors taxes : ce qui est chargé au projet à la
    #: sortie. 4 décimales : une vis ou un connecteur vaut quelques sous.
    cout_unitaire: Mapped[Optional[float]] = mapped_column(Numeric(12, 4), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
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


class InventaireMouvement(Base):
    """Une entrée, un ajustement ou une sortie d'un article."""

    __tablename__ = "inventaire_mouvements"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("inventaire_articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: entree | ajustement | sortie
    type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    #: Variation du stock, signée : + pour une entrée, − pour une sortie,
    #: l'écart compté pour un ajustement.
    quantite: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    #: Coût unitaire HT du mouvement (prix payé à l'entrée, coût moyen
    #: chargé à la sortie).
    cout_unitaire: Mapped[Optional[float]] = mapped_column(Numeric(12, 4), nullable=True)
    #: Projet chargé par une sortie (celui de l'achat au moment de la
    #: sortie ; l'achat lié fait foi s'il a été déplacé depuis).
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Achat « inventaire » créé sur le projet par une sortie.
    achat_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("achats.id", ondelete="SET NULL"), nullable=True, index=True
    )
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    #: selectin : la liste générique MCP (activity.list_entities) fait un
    #: select nu ; en async, un chargement paresseux lèverait
    #: MissingGreenlet.
    article: Mapped["InventaireArticle"] = relationship(lazy="selectin")
