"""Agenda — calendar event partagé entre Construction et Prospection.

Un AgendaEvent appartient à un volet (`scope`) :
- "construction" : visite chantier, livraison, réunion projet…
- "prospection" : RDV propriétaire, appel, visite drive-by ciblée…

Quand on consulte l'agenda d'un volet, les events de l'AUTRE volet
appartenant au même utilisateur s'affichent comme des blocs opaques
« Indisponible » (sans titre ni détails). Préserve la vie privée
inter-équipe + permet de planifier sans conflit.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class AgendaEvent(Base, TimestampUpdateMixin):
    __tablename__ = "agenda_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    all_day: Mapped[bool] = mapped_column(nullable=False, default=False)

    # Volet auquel appartient l'event. Détermine où il apparaît en clair
    # (vs comme bloc opaque dans le volet opposé).
    scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="construction",
        server_default="construction",
        index=True,
    )

    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Phase de chantier liée (ex. « Livraison conteneur 8h » sous la
    # phase « Démolition »). Permet d'afficher l'event sous la phase
    # dans l'onglet Planification du projet, et dans les calendriers
    # agenda. Plus de doublon entre événements et planification.
    phase_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("project_phases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assignee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Prospect tied to this event (e.g. scheduled visit to quote the
    # work). When set, we auto-send a confirmation email on create and
    # a 24h reminder via cron.
    contact_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Lead Prospection lié (RDV avec un propriétaire repéré).
    lead_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("prospection_leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # User assigné — utilisé surtout côté Prospection où les
    # prospecteurs n'ont pas forcément de ligne Employe (pas de
    # paie horaire). Côté Construction on garde `assignee_id`
    # (Employe) pour compatibilité.
    assignee_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(String(32), nullable=False, default="chantier")
    # e.g. chantier, visite, reunion, livraison, rdv, appel

    # Marker for the 24h reminder cron so we don't send twice.
    reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmation_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Email d'invitation envoyé à l'assigné (avec lien de confirmation).
    invitation_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Quand l'assigné a confirmé l'invitation via le lien email.
    invitation_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
