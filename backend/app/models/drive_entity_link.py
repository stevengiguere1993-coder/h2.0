"""DriveEntityLink — mapping entité Kratos ↔ dossier Drive.

Une seule ligne par couple (entity_type, entity_id) — c'est la table
qu'on consulte depuis chaque page entité pour savoir QUEL dossier Drive
afficher dans le composant <DriveFolderExplorer> (Phase 3).

drive_folder_name / drive_folder_path sont des caches : on les rafraîchit
à chaque navigation pour afficher des breadcrumbs corrects sans appel
Drive API supplémentaire. Si Drive renomme/déplace le dossier hors
Kratos, l'UI le détectera au prochain refresh et mettra à jour les
caches.

Phase 1 = table créée. La table sera peuplée Phase 3 (UI explorer +
boutons "Lier un dossier") et Phase 4-5 (Conventions, création auto).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DriveEntityLink(Base):
    __tablename__ = "drive_entity_links"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            name="uq_drive_entity_links_entity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Type d'entité Kratos (cf. DriveConvention.entity_type).
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    entity_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )
    # Id Drive du dossier (file.id côté Google Drive API).
    drive_folder_id: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    # Caches affichage. Rafraîchis à chaque navigation explorer.
    drive_folder_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    drive_folder_path: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # NULL si le lien a été créé manuellement (bouton "Lier un dossier"),
    # FK si la création vient d'une convention auto-déclenchée.
    convention_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("drive_conventions.id", ondelete="SET NULL"),
        nullable=True,
    )
