"""DrivePageModule — activation de la section Drive par type de page entité.

Phase 7. Une ligne par ``entity_type`` (ex. ``ProspectionDeal``,
``DevlogClient``). Elle pilote l'affichage du composant
``<EntityDriveSection>`` sur les pages d'entités Kratos :

- ``active=False`` (défaut) → la section Drive est totalement masquée
  sur la page de ce type d'entité (zéro pollution visuelle).
- ``active=True`` → la page affiche un titre (``display_title`` ou un
  libellé par défaut) puis le dossier Drive lié (via
  ``DriveEntityLink``) ou un encart "lier / créer un dossier".

Phil active/désactive chaque type depuis ``/parametres/drive`` (section
"Sections Drive par page"). Le pré-câblage des pages reste invisible
tant que le module n'est pas activé — aucun risque à câbler en avance.

La table est seedée au boot (1 ligne inactive par type connu) de façon
idempotente, cf. :mod:`app.services.drive_page_modules_seed`.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DrivePageModule(Base):
    __tablename__ = "drive_page_modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Type d'entité Kratos (PascalCase, aligné sur le registry des
    # conventions : ProspectionDeal, DevlogClient, ...). Unique : un
    # module par type de page.
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    # Section Drive affichée sur les pages de ce type ? Défaut False.
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Titre affiché au-dessus de l'explorer Drive. NULL → libellé par
    # défaut ("Documents Drive") côté composant.
    display_title: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    # Ordre d'affichage dans le tableau de configuration Settings.
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # Métadonnées du registry (seedées, cf. drive_page_modules_seed) qui
    # alimentent la navigation par pôle dans la page Settings. Nullables
    # pour les types auto-créés via PATCH sans passer par le seed.
    # Pôle métier : Construction, Prospection, Développement logiciel,
    # Gestion d'entreprises, Gestion immobilière.
    pole: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Libellé lisible de la page (ex. "Deal Pipeline", "Client").
    label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Route de la page d'entité (ex. "/prospection/pipeline/[id]").
    route: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
