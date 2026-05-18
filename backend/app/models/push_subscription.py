"""WebPush subscription — un user peut avoir plusieurs subscriptions
(une par appareil : téléphone iOS, téléphone Android, ordi). Sert à
envoyer des notifications push réveillant l'app même fermée :
- appels entrants (réveille l'écran pour décrocher dans le portail)
- SMS reçus liés à un contact CRM assigné à l'user
- urgences locataires (broadcast à tous les owners)

Stockage : endpoint + p256dh + auth (selon le RFC WebPush). Suppression
en cascade si l'user est supprimé. `endpoint` unique pour éviter les
doublons quand un même appareil re-souscrit.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    endpoint: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True
    )
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    auth: Mapped[str] = mapped_column(String(255), nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
