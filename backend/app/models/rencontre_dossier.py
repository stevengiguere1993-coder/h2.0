"""Dossiers suivis d'une rencontre à l'autre + consignes à Kratos (2026-11-13).

Steven : « j'aimerais avoir un tableau de vue d'ensemble des différents
dossiers en cours que nous discutons lors des rencontres », choix « tout
automatique » avec une IA qui liste et élimine les doublons, puis « que
les tableaux, les résumés et les bilans s'ajustent à travers le temps
selon mes différentes demandes de modifications ».

- ``RencontreDossier`` : un sujet qui revient d'une rencontre à l'autre
  (le camion, les électros d'Adam…). Ses champs d'état (statut, dernier
  état, prochaine action) sont RECALCULÉS à partir de ses mentions ; une
  fusion est « douce » (``fusionne_dans_id``) pour pouvoir se défaire.
- ``RencontreDossierMention`` : ce qu'UNE rencontre a dit d'un dossier —
  l'historique. ``dossier_origine_id`` garde le dossier d'avant fusion.
- ``RencontreDossierDoublon`` : paire de dossiers peut-être en double,
  et la décision prise (fusionnés / gardés séparés — jamais reproposée).
- ``RencontreConsigne`` : demande de modification retenue, redonnée à
  l'IA à chaque résumé, tableau et réponse.

Nouvelles tables → ``ensure_rencontre_dossier_tables`` (db/session.py).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class DossierStatut(str, Enum):
    EN_COURS = "en_cours"
    EN_ATTENTE = "en_attente"
    BLOQUE = "bloque"
    REGLE = "regle"


STATUTS_DOSSIER: tuple[str, ...] = tuple(s.value for s in DossierStatut)

#: Portées d'une consigne : où elle s'applique.
PORTEES_CONSIGNE: tuple[str, ...] = ("tout", "resumes", "dossiers")


class RencontreDossier(Base, TimestampUpdateMixin):
    __tablename__ = "rencontre_dossiers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    titre: Mapped[str] = mapped_column(String(255), nullable=False)
    statut: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=DossierStatut.EN_COURS.value,
        server_default=DossierStatut.EN_COURS.value,
        index=True,
    )
    entreprise_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("entreprises.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: Immeuble / projet visé, texte libre (« 1660 Saint-Clément »).
    contexte: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    responsable: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    dernier_etat: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prochaine_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Échéance telle que dite (« mercredi 13 h 30 ») et, quand elle se
    #: résout, sa date (sert au repère « en retard »).
    echeance: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    echeance_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    derniere_discussion: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True
    )
    #: Autres noms du même dossier — JSON liste (titres vus par l'IA,
    #: titres des dossiers fusionnés). Sert au rattachement.
    alias_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Champs d'identité saisis à la main (titre, responsable,
    #: entreprise_id, contexte) — JSON liste. L'IA ne les réécrit jamais.
    champs_manuels_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    #: Dernière modification manuelle de l'ÉTAT (statut, dernier état,
    #: prochaine action, échéance). Elle tient jusqu'à ce qu'une rencontre
    #: plus récente reparle du dossier.
    etat_manuel_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: 'ia' (détecté dans une rencontre) | 'manuel' (créé à la main).
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ia", server_default="ia"
    )

    # ── Fusion douce (réversible) ──
    fusionne_dans_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("rencontre_dossiers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    fusionne_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fusion_auto: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    fusion_raison: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class RencontreDossierMention(Base, TimestampUpdateMixin):
    __tablename__ = "rencontre_dossier_mentions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    dossier_id: Mapped[int] = mapped_column(
        ForeignKey("rencontre_dossiers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Dossier d'origine quand la mention a été déplacée par une fusion
    #: (sert à défaire la fusion). NULL = jamais déplacée.
    dossier_origine_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    rencontre_id: Mapped[int] = mapped_column(
        ForeignKey("rencontres.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Ce qui a été dit du dossier dans cette rencontre.
    resume: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: État du dossier APRÈS cette rencontre (1-2 phrases).
    etat: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    statut: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    responsable: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    prochaine_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    echeance: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    echeance_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    decisions_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: JSON [{"title", "owner", "due"}].
    actions_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    questions_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class RencontreDossierDoublon(Base, TimestampUpdateMixin):
    __tablename__ = "rencontre_dossier_doublons"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    #: Toujours rangés ``dossier_a_id < dossier_b_id``.
    dossier_a_id: Mapped[int] = mapped_column(
        ForeignKey("rencontre_dossiers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dossier_b_id: Mapped[int] = mapped_column(
        ForeignKey("rencontre_dossiers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raison: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: 'propose' (à trancher) | 'fusionne' | 'separes' (gardés séparés :
    #: jamais reproposés ni fusionnés d'office).
    statut: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="propose",
        server_default="propose",
        index=True,
    )
    decide_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RencontreConsigne(Base, TimestampUpdateMixin):
    __tablename__ = "rencontre_consignes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    #: 'tout' | 'resumes' (résumés et rapports) | 'dossiers' (tableau).
    portee: Mapped[str] = mapped_column(
        String(16), nullable=False, default="tout", server_default="tout"
    )
    texte: Mapped[str] = mapped_column(Text, nullable=False)
    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
