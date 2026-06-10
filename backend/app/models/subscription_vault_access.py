"""SubscriptionVaultAccess — liste des utilisateurs autorisés au coffre.

Le coffre « Abonnements » (coûts + mots de passe) n'est PAS visible par
tout le monde. La présence d'une ligne ici = cet utilisateur a accès.
Le propriétaire (rôle ``owner``) a toujours accès implicitement et c'est
lui qui gère la liste (cf. endpoints ``/subscriptions/access``).

Une seule ligne par utilisateur (contrainte d'unicité).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SubscriptionVaultAccess(Base, TimestampMixin):
    __tablename__ = "subscription_vault_accesses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # Qui a accordé l'accès (le proprio en général). Trace, pas une FK dure.
    granted_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # created_at (hérité de TimestampMixin) = date d'octroi de l'accès.
    created_at: Mapped[datetime]
