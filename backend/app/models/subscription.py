"""Subscription — un abonnement / logiciel de la compagnie.

Sert à deux choses :
  1. Suivi des coûts : tout abonnement a un coût + un cycle (mensuel /
     annuel), pour calculer ce que la compagnie dépense en logiciels.
  2. Coffre à accès : un compte « partagé » (``kind="shared"``) peut
     stocker des identifiants (courriel + mot de passe CHIFFRÉ). Un
     abonnement « personnel » (``kind="personal"``) n'a pas de mot de
     passe — seul son coût compte dans le total.

Le mot de passe n'est JAMAIS stocké en clair : ``secret_ciphertext``
contient un blob Fernet produit par :mod:`app.services.secret_vault`.
L'accès à la table entière est restreint à une liste d'utilisateurs
autorisés (cf. :class:`SubscriptionVaultAccess`).
"""

from datetime import date
from typing import Optional

from sqlalchemy import (
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class Subscription(Base, TimestampUpdateMixin):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # Catégorie libre : IA, Hébergement, Design, Comptabilité, etc.
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # "shared" (compte commun avec identifiants) | "personal" (perso, coût seul)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="shared", server_default="shared"
    )
    url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Coût + cycle de facturation. On stocke le montant tel que facturé et
    # le cycle ; la conversion mensuelle/annuelle se fait à l'affichage.
    cost: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="CAD", server_default="CAD"
    )
    # "monthly" | "yearly"
    billing_cycle: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="monthly",
        server_default="monthly",
    )
    next_renewal_at: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
    # Moyen de paiement / qui paie (libellé libre : « Visa ···6411 »…)
    paid_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Pour un abonnement personnel : à qui il appartient.
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Identifiants (optionnels — seulement pour les comptes partagés).
    login_username: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True
    )
    # Mot de passe CHIFFRÉ (blob Fernet). Jamais en clair. NULL = pas de
    # mot de passe stocké (perso / sensible).
    secret_ciphertext: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_by_email: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True
    )
