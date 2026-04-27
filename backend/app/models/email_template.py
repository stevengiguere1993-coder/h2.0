"""Templates de courriels pour les relances commerciales.

Permet aux managers de définir des messages-types (relance après
soumission, message de bienvenue, demande de signature, etc.) avec
des variables interpolées au moment de l'envoi (`{{nom}}`,
`{{adresse}}`, `{{soumission_id}}`, etc.).

L'envoi passe par Microsoft Graph (déjà branché pour les soumissions)
— pas de coût supplémentaire si le compte M365 du business est connecté.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class EmailTemplate(Base, TimestampUpdateMixin):
    __tablename__ = "email_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Sujet et corps avec placeholders {{var}}.
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    # Catégorie d'usage pour filtrer dans l'UI : « relance »,
    # « bienvenue », « signature », « rappel paiement », « custom ».
    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="custom",
        server_default="custom",
        index=True,
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
