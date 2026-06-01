"""DriveConvention — règle configurable Entité Kratos ↔ Dossier Drive.

Une convention décrit COMMENT et QUAND créer/lier un dossier Drive à une
entité Kratos (deal, projet, client, soumission). Exemples :

  - "Quand un deal Prospection passe au statut 'analyse', créer un dossier
    sous /Pipeline/<nom_deal> en clonant le template 'AnalyseTemplate'."
  - "Quand un projet Construction est créé, créer un dossier sous
    /Projets/<numero_projet> - <adresse> avec les sous-dossiers Plans,
    Photos, Factures."

UI de configuration : Phase 4 (page /parametres/drive > Conventions).
Exécution : Phase 4-5 (event listeners SQLAlchemy ou hooks endpoints).

Phase 1 = table créée vide. Aucune UI ni runtime ne la consulte encore.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DriveConvention(Base):
    __tablename__ = "drive_conventions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # entity_type — sur quel type d'entité Kratos la convention s'applique.
    # Valeurs typiques : "prospection_deal", "project", "devlog_project",
    # "client", "soumission", "devlog_soumission".
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    # trigger_event — quand la convention se déclenche.
    # "created" : à la création de l'entité.
    # "status_changed" : à chaque changement de statut (utilisé avec
    #     status_to_parent_map pour déplacer le dossier selon le statut).
    trigger_event: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    # Id Drive du dossier parent (où créer le sous-dossier de l'entité).
    parent_folder_drive_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    # Template de nom du dossier — supporte des placeholders du type
    # "{nom}", "{numero}", "{adresse}". Substitution faite au runtime
    # depuis les champs de l'entité Kratos.
    folder_name_template: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # Id Drive d'un dossier template à CLONER (Phase 4-5 : copy_folder via
    # Drive API). Si NULL → on crée un dossier vide.
    template_folder_to_copy_drive_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    # Liste JSON des sous-dossiers à créer à l'intérieur du dossier de
    # l'entité (ex. ["Plans", "Photos", "Factures"]).
    subfolders_to_create: Mapped[Optional[Any]] = mapped_column(
        JSON, nullable=True
    )
    # Si True, on crée également une DriveEntityLink pointant vers le
    # dossier créé (lien entité ↔ dossier visible dans <DriveFolderExplorer>).
    auto_link_to_entity: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    # Mapping JSON "statut → drive_folder_id parent" pour les conventions
    # de type "status_changed" : quand l'entité passe au statut X, on
    # déplace son dossier sous le parent associé. Ex.
    # {"won": "<id_drive_dossier_gagne>", "lost": "<id_drive_dossier_perdu>"}.
    status_to_parent_map: Mapped[Optional[Any]] = mapped_column(
        JSON, nullable=True
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    # Ordre d'évaluation quand plusieurs conventions matchent le même
    # event (priorité décroissante : plus haut = appliqué en premier).
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100
    )

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
    # Notes libres (rationale, description fonctionnelle pour Phil).
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
