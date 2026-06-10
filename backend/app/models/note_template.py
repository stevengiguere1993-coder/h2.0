"""NoteTemplate — note prédéfinie réutilisable.

Catalogue de notes types (conditions de paiement, mentions légales,
particularités d'un chantier…) qu'un utilisateur peut insérer dans la
note d'une soumission puis personnaliser. Calqué sur les modèles de
courriels (`email_templates`) : un simple CRUD de texte réutilisable.
"""

from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class NoteTemplate(Base, TimestampUpdateMixin):
    __tablename__ = "note_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Libellé court affiché dans le sélecteur (ex. « Paiement 50/50 »).
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Le texte de la note, inséré tel quel dans la soumission.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Regroupement libre (ex. "paiement", "garantie", "chantier").
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="general", server_default="general",
        index=True,
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
