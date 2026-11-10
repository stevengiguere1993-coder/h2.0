"""Admin locative (Phil 2026-11-10) — Gestion immobilière.

« Appelle cette nouvelle section : Admin locative. Car tu vas y mettre aussi la
possibilité d'envoyer des avis de renouvellement… crée une genre de mini base de
données des contacts dans cette section uniquement. Donc une fois une personne
créée, je peux venir la sélectionner la fois d'après. »

Deux tables, créées par ``create_all`` au démarrage (``ensure_critical_columns``) :

- ``adm_loc_contacts`` : le carnet de cette section SEULEMENT — locateurs,
  locataires et cautions de baux hors système. Rien à voir avec les fiches
  locataires de Kratos (aucun loyer, aucune facturation, aucun rent roll).
- ``adm_loc_avis`` : avis d'augmentation de loyer et de modification du bail
  (formulaire TAL-806) envoyés pour un bail hors système. Mêmes noms de champs
  que le cycle de renouvellement d'un bail Kratos (``status``,
  ``avis_envoye_le``, ``reponse_le``, ``refus_motif``, ``document_id``) : la page
  publique de réponse du locataire traite les deux de la même façon.
  L'avis porte TOUJOURS la date du jour de son envoi (jamais saisie).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import Boolean, Date, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin

#: Rôles d'un contact (simple aide au tri — une même personne peut tout faire).
CONTACT_ROLES: tuple[str, ...] = ("locateur", "locataire", "caution")

#: Statuts d'un avis. « propose » et la suite sont ceux du cycle de
#: renouvellement Kratos (page publique de réponse) ; « brouillon » = pas
#: encore envoyé ; « annule » = retiré par un humain.
AVIS_STATUTS: tuple[str, ...] = (
    "brouillon", "propose", "accepte", "refuse", "depart", "repute_accepte", "annule",
)
#: Les 3 formes de hausse du TAL-806.
AVIS_MODES: tuple[str, ...] = ("nouveau_loyer", "hausse_montant", "hausse_pct")


class AdmLocContact(Base, TimestampUpdateMixin):
    __tablename__ = "adm_loc_contacts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nom: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    telephone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    courriel: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    adresse: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    #: Dernier rôle tenu (locateur | locataire | caution).
    role: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Faux = retiré du carnet (jamais supprimé : il reste lisible sur les baux passés).
    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", index=True
    )
    created_by_email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


class AdmLocAvis(Base, TimestampUpdateMixin):
    __tablename__ = "adm_loc_avis"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    #: Nom interne (« Renouvellement Marc 2027 »).
    libelle: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Locateur (instantané : l'avis reste lisible même si le contact change).
    locateur_nom: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    locateur_adresse: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    locateur_telephone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    locateur_courriel: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    # Locataire.
    locataire_nom: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    locataire_courriel: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    # Logement.
    logement_adresse: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    logement_numero: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    logement_ville: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Bail en cours.
    bail_date_debut: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    bail_date_fin: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    loyer_actuel: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)

    # Modification proposée (une des 3 formes du TAL-806) + nouvelle période.
    modif_mode: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    nouveau_loyer: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    hausse_montant: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    hausse_pct: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    nouvelle_date_debut: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    nouvelle_date_fin: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    autres_modifications: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Cycle — mêmes noms que imm_bail_renouvellements (page publique).
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="brouillon", server_default="brouillon", index=True
    )
    #: Date de l'envoi = date imprimée sur l'avis. Posée par l'envoi, jamais saisie.
    avis_envoye_le: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    reponse_le: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    refus_motif: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Le PDF de l'avis (imm_documents « avis_modification », sans rattachement).
    document_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    envoye_a: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by_email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


__all__ = ["AdmLocContact", "AdmLocAvis", "CONTACT_ROLES", "AVIS_STATUTS", "AVIS_MODES"]
