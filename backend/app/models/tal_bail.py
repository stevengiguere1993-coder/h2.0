"""Bail de logement OFFICIEL généré par l'API du TAL (formulaire 53000BAIL).

Trois tables, créées par ``create_all`` au démarrage (filet
``ensure_critical_columns``) :

- ``tal_schemas`` : versions du schéma de formulaire fourni par le TAL
  (JSON ``structurePreRemplissage`` + ``champs``). Une seule version
  ACTIVE ; à défaut, le fichier embarqué ``app/assets/tal/``. Le TAL
  donne 15 jours pour absorber un changement de schéma → on téléverse la
  nouvelle version, on lit le diff, on active.
- ``tal_connexion`` : UNE ligne — mode (simulation | reel), URL de base,
  nom de l'en-tête de la clé, chemins FRW111/FRW122 et la clé API
  CHIFFRÉE (Fernet, coffre ``secret_vault``). Décision Phil 2026-10-15 :
  la clé vit dans Kratos (Paramètres), jamais dans le client, les
  journaux ni Git. Elle n'est jamais relue par l'API — seulement
  « configurée : oui/non ».
- ``tal_transmissions`` : chaque demande de bail. Cycle :
  brouillon → (FRW111) forme_creee → (FRW122) transmise ; echec (erreur
  à l'une des étapes, relançable sans second FRW111 — jamais deux
  formulaires facturés pour un même bail) ; annulee. Garde le ShortGuid,
  le numéro de confirmation, les messages du TAL, le PDF archivé
  (``imm_documents``), le coût (2,99 $ en mode réel) et le frais
  refacturé au propriétaire (``imm_frais_manuels_gestion``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampUpdateMixin

#: Statuts d'une transmission.
TRANSMISSION_STATUTS: tuple[str, ...] = (
    "brouillon",     # formulaire préparé dans Kratos, rien envoyé
    "forme_creee",   # FRW111 fait (ShortGuid), FRW122 pas encore réussi
    "transmise",     # FRW122 fait : PDF reçu et archivé — FACTURABLE
    "echec",         # erreur avant d'avoir un ShortGuid (relançable)
    "annulee",       # abandonnée par un humain (brouillon ou échec)
)
STATUTS_OUVERTS: tuple[str, ...] = ("brouillon", "forme_creee", "echec")


class TalSchema(Base):
    __tablename__ = "tal_schemas"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    type_formulaire: Mapped[str] = mapped_column(
        String(32), nullable=False, default="53000BAIL", server_default="53000BAIL"
    )
    #: Version lisible (date du fichier TAL ou libellé saisi).
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Nom du fichier téléversé.
    source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    #: Le JSON complet du TAL (jamais chargé dans les listes).
    json_text: Mapped[Optional[str]] = deferred(mapped_column(Text, nullable=True))
    nb_champs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    uploaded_by_email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TalConnexion(Base):
    __tablename__ = "tal_connexion"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    #: simulation (défaut : aucun appel, PDF marqué) | reel.
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="simulation", server_default="simulation"
    )
    api_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    entete_cle: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    chemin_frw111: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    chemin_frw122: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    #: Clé API du TAL, chiffrée (Fernet). Jamais renvoyée par l'API.
    cle_chiffree: Mapped[Optional[str]] = deferred(mapped_column(Text, nullable=True))
    cle_posee_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cle_posee_par: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by_email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


class TalTransmission(Base, TimestampUpdateMixin):
    __tablename__ = "tal_transmissions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    #: Bail Kratos (proposé) pour lequel le formulaire est produit. SET
    #: NULL si le bail est supprimé (désistement) : une transmission
    #: facturée ne disparaît jamais — les instantanés ci-dessous restent.
    bail_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_baux.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dossier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_location_dossiers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    logement_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    immeuble_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    locataire_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    #: Adresse du logement au moment de la demande (lisible sans jointure).
    adresse: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    statut: Mapped[str] = mapped_column(
        String(16), nullable=False, default="brouillon", server_default="brouillon", index=True
    )
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="simulation", server_default="simulation"
    )
    schema_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    #: Le formulaire (objet « form ») tel qu'envoyé / à envoyer.
    #: Non différé : relu après commit/refresh (le chargement paresseux
    #: est impossible en async) ; ~15 Ko par ligne, listes filtrées par bail.
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Dernier rapport de validation locale.
    rapport_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Chemins pré-remplis par défaut (à vérifier par un humain).
    a_verifier_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    #: Notre identifiant de suivi transmis au TAL (IdentifiantUtilisateur).
    identifiant_utilisateur: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    short_guid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    no_confirmation: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    messages_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Documents reçus (nom, type source, taille) — sans le base64.
    documents_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: PDF archivé (imm_documents, type « bail_tal »).
    document_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    #: Document eSign Kratos lancé sur ce PDF (signature interne, PR C).
    esign_document_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    #: Coût TAL (2,99 $ en mode réel, 0 en simulation) et frais refacturé
    #: au propriétaire (tarif Paramètres, 8,99 $ par défaut).
    cout: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)
    frais_manuel_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    frais_montant: Mapped[Optional[float]] = mapped_column(Numeric(8, 2), nullable=True)

    erreur: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tentatives: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    genere_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by_email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


__all__ = [
    "TalSchema",
    "TalConnexion",
    "TalTransmission",
    "TRANSMISSION_STATUTS",
    "STATUTS_OUVERTS",
]
