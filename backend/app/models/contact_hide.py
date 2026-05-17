"""Masquage d'un contact fédéré dans la page /entreprises/contacts.

Le user veut pouvoir retirer un sous-traitant / fournisseur / employé
partenaire de la vue rolodex **sans** le supprimer de son module
d'origine. On stocke ici les couples (source, source_id) à exclure
de la vue agrégée — c'est purement cosmétique, l'entité d'origine
reste intacte.

Note : on n'utilise pas cette table pour les contacts purs (table
`contacts`). Pour eux, on garde le DELETE direct qui retire vraiment
la ligne du rolodex.
"""

from typing import Optional

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ContactHide(Base, TimestampMixin):
    __tablename__ = "contact_hides"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_contact_hide"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Source de l'entité masquée : "sous_traitant" |
    # "devlog_sous_traitant" | "fournisseur" | "employe_partner".
    # String libre pour pouvoir ajouter de nouvelles sources sans
    # migration.
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    hidden_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    # `created_at` (du mixin) = quand on a masqué.

    def __repr__(self) -> str:
        return (
            f"<ContactHide(source='{self.source}', "
            f"source_id={self.source_id})>"
        )
