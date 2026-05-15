"""Lead (prospect) du pipeline CRM — pôle Développement logiciel.

Mirror structurel de `ContactRequest` côté Construction : mêmes
statuts (new/contacted/qualified/quoted/won/lost/spam), mêmes champs
(address, project_type, kanban_column, etc.) pour permettre le clonage
1:1 de la page CRM côté frontend.

Les anciens noms `project_summary` / `notes` sont conservés en DB pour
préserver les données déjà saisies ; un alias serveur les expose sous
`message` / `internal_notes` (les noms attendus par la page clonée).
"""

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin

#: Statuts pipeline — alignés sur ContactRequest pour identité visuelle.
LEAD_STATUSES = (
    "new",
    "contacted",
    "meeting",
    "qualified",
    "quoted",
    "won",
    "lost",
    "spam",
)

#: Types de projets de développement (équivalent ProjectType côté
#: Construction). Garde les mêmes patterns pour le frontend.
LEAD_PROJECT_TYPES = (
    "web_app",
    "mobile_app",
    "automation",
    "integration",
    "consulting",
    "autre",
)


class DevlogLead(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_leads"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Lieu du projet (adresse client ou siège de la boîte).
    address: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )

    # Type de projet (cf. LEAD_PROJECT_TYPES).
    project_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="autre",
        server_default="autre",
    )

    # Origine : "interne" / "web" / libre.
    source: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )

    # Étape du pipeline (cf. LEAD_STATUSES).
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="new",
        server_default="new", index=True,
    )
    # Free-form kanban column label (mêmes patterns que ContactRequest)
    # → permet d'avoir des colonnes custom au-delà des statuts.
    kanban_column: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    # Ordre dans la colonne du kanban.
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Locale du formulaire web (fr / en).
    locale: Mapped[str] = mapped_column(
        String(8), nullable=False, default="fr", server_default="fr"
    )

    # Closer responsable du lead.
    assigned_to_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Description du projet — équivalent ContactRequest.message.
    # NOM DB : project_summary (legacy, conservé). Exposé en API
    # comme `message` via le schéma Pydantic.
    project_summary: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    budget_range: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    # Notes internes — équivalent ContactRequest.internal_notes.
    # NOM DB : notes (legacy, conservé). Exposé en API comme
    # `internal_notes`.
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Rempli quand le lead est converti en client (statut « won »).
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("devlog_clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<DevlogLead(id={self.id}, name='{self.name}', status='{self.status}')>"
