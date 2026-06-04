"""UserImmeuble — affectation user↔immeuble pour que les utilisateurs de
rôle `employee` ne voient que les immeubles auxquels on les a affectés.

owner / admin / manager ignorent complètement cette table (ils voient tous
les immeubles). Un employé ne voit que les immeubles où une ligne existe
pour son user_id.

Nouvelle table → créée par `create_all` (pas de migration nécessaire).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, PrimaryKeyConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserImmeuble(Base):
    __tablename__ = "user_immeubles"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "immeuble_id", name="pk_user_immeubles"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
