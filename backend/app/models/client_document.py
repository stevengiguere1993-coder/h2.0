"""Document rattaché à une fiche client.

Typiquement le contrat d'entreprise signé par les deux parties, archivé
automatiquement dans le profil du client à la signature en ligne. Peut
aussi servir à d'autres pièces (manuelles) plus tard.
"""

from typing import Optional

from sqlalchemy import ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampMixin


class ClientDocument(Base, TimestampMixin):
    __tablename__ = "client_documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="application/pdf",
        server_default="application/pdf",
    )
    # Origine du document : "contract" (contrat signé auto-archivé),
    # "manual" (téléversé par le staff), etc.
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Soumission / contrat d'origine, quand applicable.
    soumission_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("soumissions.id", ondelete="SET NULL"), nullable=True
    )
    # Contenu binaire — deferred pour ne jamais le charger dans les
    # listes (seul l'endpoint de téléchargement le tire).
    blob: Mapped[bytes] = deferred(
        mapped_column(LargeBinary, nullable=False)
    )
