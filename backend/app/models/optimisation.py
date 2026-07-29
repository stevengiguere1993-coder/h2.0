"""Projets d'OPTIMISATION d'immeuble (pôle Gestion d'entreprise).

Un projet = une INC (entreprise) + un immeuble fraîchement acquis, avec
trois suivis (vision Phil 2026-07-29) :

1. BUDGET — lignes de budget posées au départ (Frais professionnels,
   Travaux, Négociation…), chacune mappée à un ou plusieurs comptes du
   plan comptable QuickBooks. Le « dépensé » réel est lu LIVE via l'API
   QBO (jamais stocké, jamais écrit vers QBO) → reste = budget − dépensé.
2. OBJECTIFS — revenus/dépenses projetés vs le réel tiré de la Gestion
   locative (baux actifs, dépenses d'immeuble) : rendu où, manque
   combien.
3. NÉGOCIATIONS — suivi locataire par locataire déjà en place (reste /
   quitte, entente, indemnité, timeline d'événements datés).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class OptimisationProjet(Base, TimestampUpdateMixin):
    __tablename__ = "optimisation_projets"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    #: L'INC porteuse du projet.
    entreprise_id: Mapped[int] = mapped_column(
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    #: L'immeuble optimisé (source des réels locatifs).
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    #: actif | termine
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="actif", server_default="actif"
    )

    #: Début du projet — borne basse des dépenses QBO comptées.
    date_debut: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    #: Connexion QuickBooks à interroger ("entreprise" | "immobilier" |
    #: "construction"). Choisie par projet : chez Phil les INC peuvent
    #: partager un fichier QBO ou avoir le leur.
    qbo_scope: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )

    #: Objectifs de croisière (comparés au réel locatif).
    objectif_revenus_mensuels: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    objectif_depenses_mensuelles: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    #: Objectifs libres additionnels — JSON [{"label", "cible", "actuel"}]
    #: (« etc. » de Phil : valeur de revente visée, cap rate…).
    objectifs_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class OptimisationBudgetLigne(Base, TimestampUpdateMixin):
    """Une enveloppe de budget (ex. « Frais professionnels » 25 000 $)
    mappée à des comptes du plan comptable QBO."""

    __tablename__ = "optimisation_budget_lignes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    projet_id: Mapped[int] = mapped_column(
        ForeignKey("optimisation_projets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    nom: Mapped[str] = mapped_column(String(255), nullable=False)
    budget_montant: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0
    )

    #: Comptes QBO dont les dépenses comptent dans cette enveloppe —
    #: JSON [{"id": "123", "name": "Frais professionnels"}]. Les noms
    #: sont dénormalisés pour l'affichage hors connexion.
    qbo_accounts_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    position: Mapped[int] = mapped_column(nullable=False, default=0)


class OptimisationNego(Base, TimestampUpdateMixin):
    """Suivi de négociation avec UN locataire en place."""

    __tablename__ = "optimisation_negos"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    projet_id: Mapped[int] = mapped_column(
        ForeignKey("optimisation_projets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    #: Lien vers le vrai locataire du locatif quand il existe (SET NULL
    #: si la fiche locataire est supprimée — la négo garde son histoire).
    locataire_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_locataires.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    #: Dénormalisés pour l'affichage (survivent au SET NULL).
    nom_locataire: Mapped[str] = mapped_column(String(255), nullable=False)
    logement_label: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    loyer_actuel: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    #: en_place | a_contacter | en_discussion | entente | depart_prevu |
    #: parti | reste
    statut: Mapped[str] = mapped_column(
        String(24), nullable=False,
        default="en_place", server_default="en_place",
    )

    #: Type d'entente : cash_for_raise | cash_for_keys | renovation |
    #: autre. Colonne additive → ensure_critical_columns.
    type_entente: Mapped[Optional[str]] = mapped_column(
        String(24), nullable=True
    )

    #: Résumé de l'entente prise (texte libre) + montant en jeu
    #: (indemnité de départ, nouveau loyer…) + date visée.
    entente: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    montant_entente: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    date_cible: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    #: Timeline d'événements — JSON [{"date": "2026-07-29", "texte": …}].
    events_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    position: Mapped[int] = mapped_column(nullable=False, default=0)
