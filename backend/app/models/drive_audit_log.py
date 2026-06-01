"""DriveAuditLog — journal dédié des actions Google Drive.

Séparé du AuditLog général (app.models.audit_log) pour deux raisons :

  1. Volume : la navigation Drive (list_folder, preview) peut générer
     beaucoup d'événements ; on ne veut pas polluer le journal général.
  2. Champs spécifiques : drive_file_id / drive_file_name / google_email
     sont utiles uniquement pour la traçabilité Drive.

Toute action mutation côté Drive (create_folder, upload, rename, move,
delete, share) DOIT poser une ligne ici, avec ``success=True`` ou
``False`` + ``error_message`` en cas d'échec.

UI de consultation : Phase 4 (page /parametres/drive > Audit log).

Phase 1 = table créée + helper d'insertion (`drive_oauth` la peuple lors
des connexions/déconnexions/refresh).
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


class DriveAuditLog(Base):
    __tablename__ = "drive_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Email Google associé à l'action (peut différer du user.email Kratos
    # quand le user a connecté un compte Gmail perso).
    google_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    # action — verbe précis. Valeurs reconnues Phase 1 :
    #   drive_user_token.connected
    #   drive_user_token.disconnected
    #   drive_user_token.token_refreshed
    #   drive_user_token.refresh_failed
    # Valeurs Phase 2+ (wrapper Drive API) :
    #   list_folder, upload, rename, move, delete, share, download,
    #   create_folder, preview
    action: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    drive_file_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )
    drive_file_name: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    entity_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    entity_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    details: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
