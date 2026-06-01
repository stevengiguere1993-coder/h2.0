"""DriveAutoUpload — règle configurable d'auto-upload de PDF Kratos vers Drive.

À chaque fois que Kratos génère un PDF (fiche d'analyse Prospection, NDA
signé, soumission Construction, offre PPTX, facture Dev logiciel), on
peut configurer un dépôt automatique dans un sous-dossier de l'entité
liée — sans intervention humaine.

Exemples de règles :

  - "Toute nouvelle fiche d'analyse → /Pipeline/<deal>/Analyse/<date>.pdf"
  - "Tout NDA signé → /Pipeline/<deal>/NDA signe.pdf (overwrite)"
  - "Toute facture Dev logiciel envoyée → /Clients/<client>/Facturation/
    F-<numero>.pdf (versioning)"

UI de configuration : Phase 4 (page /parametres/drive > Auto-upload).
Exécution : Phase 5-6 (hooks sur les services de génération PDF).

Phase 1 = table créée vide.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
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


class DriveAutoUpload(Base):
    __tablename__ = "drive_auto_uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # document_type — quel PDF Kratos déclenche l'upload.
    # Valeurs reconnues : "fiche_analyse", "nda_signed", "soumission_pdf",
    # "offre_pptx", "facture_pdf".
    document_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    # entity_type sur lequel rattacher le fichier (cf. DriveEntityLink).
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    # Chemin du sous-dossier relatif au dossier de l'entité.
    # Supporte les placeholders {date}, {numero}, {annee}, etc.
    # Ex. "Analyse/{annee}/{date}" → dossier "Analyse/2026/2026-06-01".
    subfolder_path_template: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    # Template du nom de fichier (sans extension — déduite du PDF).
    # Ex. "Fiche analyse - {adresse}" → "Fiche analyse - 1234 rue X.pdf".
    file_name_template: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # Stratégie en cas de fichier existant avec le même nom.
    # "overwrite" : remplace l'ancien (drive_file_id préservé).
    # "version"   : ajoute une nouvelle révision Drive (historique conservé).
    # "keep_both" : ajoute un suffixe " (1)", " (2)", etc.
    overwrite_strategy: Mapped[str] = mapped_column(
        String(32), nullable=False, default="version"
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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
