"""NDA — Entente de confidentialité ultra-minimaliste.

Modèle dédié au formulaire « 2 champs » sur la page d'un deal du
Pipeline. Phil envoie une entente de confidentialité à un
investisseur potentiel pour pouvoir partager les informations
sensibles d'un deal (analyses financières, données locatives,
stratégie de mise en valeur).

Pattern strictement calqué sur `Offer` (PR #445) — même flow de
signature électronique via token public, mêmes statuts simplifiés.
La différence : seulement 2 champs visibles (nom + email de
l'investisseur), tout le reste est pré-rempli (Horizon comme
émetteur, durée 2 ans, juridiction Québec, propriété tirée du
deal).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class NDAStatus(str, Enum):
    """Statuts du cycle de vie d'un NDA.

    - brouillon : créé mais pas encore envoyé
    - envoye    : email parti à l'investisseur
    - signe     : investisseur a signé (peut recevoir les infos)
    - expire    : non utilisé pour l'instant — réservé si Phil veut
                  ajouter une date d'expiration plus tard
    """

    BROUILLON = "brouillon"
    ENVOYE = "envoye"
    SIGNE = "signe"
    EXPIRE = "expire"


class NDA(Base, TimestampUpdateMixin):
    """Entente de confidentialité reliée à un Deal du Pipeline."""

    __tablename__ = "ndas"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    deal_id: Mapped[int] = mapped_column(
        ForeignKey("prospection_deals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ----- Les 2 champs visibles du formulaire -----
    investor_name: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    investor_email: Mapped[str] = mapped_column(
        String(320), nullable=False
    )

    # ----- Statut & signature -----
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=NDAStatus.BROUILLON.value,
        server_default=NDAStatus.BROUILLON.value,
        index=True,
    )
    signature_token: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    signed_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # Téléphone capturé sur le formulaire public de signature. Le NDA
    # demande Nom + Email + Téléphone + Date + Signature côté Récepteur,
    # et l'email est déjà connu (lien envoyé à cette adresse) → on ne
    # collecte « en plus » que le téléphone côté formulaire public.
    signed_phone: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_ip: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ----- PDF signé (généré à la signature publique) -----
    # Stocké en BYTEA pour rester self-contained (pas de bucket
    # externe). Contient le PDF avec le bloc Récepteur rempli + le
    # bandeau emerald « SIGNEE ELECTRONIQUEMENT » + hash SHA-256.
    # Récupérable via GET /api/v1/ndas/{id}/signed-pdf (auth admin/
    # owner — audit immuable, pas re-rendu à chaque requête).
    signed_pdf_blob: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
