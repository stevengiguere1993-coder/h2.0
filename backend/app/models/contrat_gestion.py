"""Contrat de gestion immobilière — convention MGV signée par le Mandant.

Un contrat de gestion lie MGV Développement inc. (le **Mandataire**) au
propriétaire d'un ou plusieurs immeubles (le **Mandant**). Il est créé
depuis la fiche d'un immeuble (onglet « Contrat de gestion »), envoyé
pour signature en ligne au courriel du Mandant, suivi (ouvert / signé)
puis archivé.

Pattern de signature strictement calqué sur `NDA` / `Bail` :
- `signature_token` opaque (secrets.token_urlsafe) = auth + audit
- suivi `sent_at` / `opened_at` / `open_count` / `signed_at`
- PDF signé figé en BYTEA (`signed_pdf_blob`) + archivage Drive

Les 7 champs variables du contrat (compagnie, siège, représentant,
titre, adresses des immeubles, district judiciaire, courriel) sont
stockés en clair sur le contrat : ils sont pré-remplis depuis
l'Entreprise détentrice quand c'est possible, puis éditables. Le
**corps** légal complet est rendu depuis un gabarit éditable
(`ContratGestionTemplate`) et figé (`corps_markdown`) au moment de la
génération — ainsi un contrat déjà signé garde sa version, même si le
gabarit par défaut change plus tard.

Caution solidaire : par défaut le même signataire (le représentant du
Mandant garantit personnellement les obligations de sa compagnie). Une
seule signature en ligne remplit les deux blocs.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class ContratGestionStatus(str, Enum):
    """Cycle de vie d'un contrat de gestion.

    Flux à deux signatures (MGV d'abord, puis le Mandant) :
    - brouillon      : créé, pas encore envoyé (éditable)
    - attente_mgv    : envoyé au signataire MGV (Mandataire) pour la 1re signature
    - attente_client : MGV a signé, envoyé au Mandant pour la 2e signature
    - signe          : les deux ont signé (corps figé, PDF signé aux deux)
    """

    BROUILLON = "brouillon"
    ATTENTE_MGV = "attente_mgv"
    ATTENTE_CLIENT = "attente_client"
    SIGNE = "signe"


class ContratGestion(Base, TimestampUpdateMixin):
    """Convention de gestion immobilière reliée à un immeuble."""

    __tablename__ = "contrats_gestion"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Immeuble depuis la fiche duquel le contrat est créé. Un contrat
    # peut couvrir plusieurs immeubles (voir `immeubles_adresses`) mais
    # reste rattaché à celui-ci pour l'affichage dans l'onglet.
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Entreprise détentrice (le Mandant), quand connue. Sert au
    # pré-remplissage et à mémoriser les infos (siège, district…) pour
    # la prochaine fois.
    entreprise_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("entreprises.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ----- Les 7 champs variables du contrat (éditables) -----
    compagnie: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    siege_social: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    representant_nom: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    representant_titre: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    # Une adresse d'immeuble par ligne. Pré-rempli avec l'immeuble
    # courant ; Phil peut en ajouter d'autres.
    immeubles_adresses: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    district_judiciaire: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    mandant_courriel: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    # Lieu de signature (« SIGNÉE À ____, QC »). Défaut = ville de
    # l'immeuble.
    lieu_signature: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )

    # ----- Caution solidaire -----
    # Par défaut le même signataire (voir docstring module). Si Phil
    # décoche, le bloc caution est retiré du PDF.
    caution_requise: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    caution_nom: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # ----- Personnalisation par contrat (négociation) -----
    # Gabarit propre à CE contrat (avec placeholders {{...}}), quand Phil
    # négocie des clauses/frais différents pour cet immeuble. NULL = on
    # utilise le gabarit global par défaut. Éditable tant que brouillon.
    corps_template_override: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # ----- Corps légal figé à la génération -----
    # Snapshot du gabarit rendu (placeholders substitués) au moment de
    # la signature. NULL tant que non signé → rendu à la volée depuis le
    # gabarit effectif (override du contrat, sinon global).
    corps_markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ----- Statut & signature (patron NDA/Bail) -----
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ContratGestionStatus.BROUILLON.value,
        server_default=ContratGestionStatus.BROUILLON.value,
        index=True,
    )
    signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Accusé de lecture : première ouverture + dernière + compteur.
    opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    open_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    signed_ip: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    # Signature manuscrite (data-URL PNG décodée) — deferred: jamais
    # chargée sauf undefer explicite.
    signature_image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    signature_image_content_type: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )

    # ----- Signature du Mandataire (MGV), qui signe EN PREMIER -----
    # Le contrat part d'abord au signataire MGV (nom + courriel), qui
    # signe, puis est relayé automatiquement au Mandant. Colonnes
    # additives → cf. ensure_critical_columns (session.py).
    mandataire_nom: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    mandataire_courriel: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    mandataire_signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), index=True, nullable=True
    )
    mandataire_signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    mandataire_signed_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    mandataire_signed_ip: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    mandataire_signature_image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    mandataire_signature_image_content_type: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    # Accusé de lecture du MANDATAIRE — distinct de opened_at/open_count
    # qui ne comptent QUE le Mandant (bug 2026-07-10 : l'ouverture du
    # lien mandataire était attribuée au mandant dans le suivi).
    mandataire_opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    mandataire_last_opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    mandataire_open_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # PDF signé immuable (généré à la signature publique).
    signed_pdf_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )


class ContratGestionTemplate(Base, TimestampUpdateMixin):
    """Gabarit par défaut du contrat de gestion (singleton id=1).

    `corps_markdown` contient le texte légal complet avec des
    marqueurs `{{PLACEHOLDER}}` (COMPAGNIE, SIEGE_SOCIAL, REPRESENTANT,
    TITRE, IMMEUBLES, DISTRICT, COURRIEL, LIEU, DATE). Éditable en tout
    temps depuis les Paramètres (owner/admin). Les contrats déjà signés
    ne sont pas affectés (ils ont figé leur `corps_markdown`).
    """

    __tablename__ = "contrat_gestion_template"

    id: Mapped[int] = mapped_column(primary_key=True)
    corps_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
