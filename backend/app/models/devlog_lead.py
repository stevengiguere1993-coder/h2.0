"""Lead du pipeline du closer — pôle Développement logiciel.

Le closer gère ses leads à travers un pipeline kanban : nouveau →
contacté → rendez-vous → présentation → soumission → gagné / perdu.
Un lead « gagné » est converti en DevlogClient (client_id rempli).
"""

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin

#: Étapes du pipeline (colonnes du kanban du closer).
LEAD_STATUSES = (
    "nouveau",
    "contacte",
    "rdv",
    "presentation",
    "soumission",
    "gagne",
    "perdu",
)


class DevlogLead(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_leads"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Origine : "interne" (saisi par le closer) ou "web" (formulaire
    # d'un site externe — branché plus tard).
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="interne",
        server_default="interne",
    )
    # Étape du pipeline (cf. LEAD_STATUSES).
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="nouveau",
        server_default="nouveau", index=True,
    )
    # Ordre dans la colonne du kanban.
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Closer responsable du lead.
    assigned_to_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Ce que le client veut faire développer.
    project_summary: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    budget_range: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Rempli quand le lead est converti en client (statut « gagné »).
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<DevlogLead(id={self.id}, name='{self.name}', status='{self.status}')>"
