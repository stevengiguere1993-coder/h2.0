"""Bloc-notes de la zone employés (Steven, bug 13, 2026-10-18).

Une note est une petite tâche ou un pense-bête rattaché au bloc-notes
d'UN utilisateur (le destinataire). Deux usages :

- l'employé s'écrit ses propres notes (auteur = destinataire) ;
- un admin ou un propriétaire « envoie » une note à n'importe quel
  employé depuis la zone employés (auteur ≠ destinataire) ; l'employé
  reçoit une notification (cloche + push) et la note apparaît dans son
  bloc-notes avec la mention « Nouveau » jusqu'à ce qu'il l'ouvre.

Qui voit quoi : le destinataire voit son bloc-notes, l'auteur revoit ce
qu'il a envoyé, les admins et propriétaires voient tout (par employé).
Volontairement simple — pas de statut kanban ni de scoring : une case à
cocher « fait », un titre optionnel, une échéance optionnelle.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class BlocNote(Base, TimestampUpdateMixin):
    __tablename__ = "bloc_notes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    #: Bloc-notes auquel la note appartient (l'employé qui doit la voir).
    destinataire_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Qui l'a écrite : l'employé lui-même ou l'admin / propriétaire qui
    #: l'a envoyée. NULL si le compte auteur a été supprimé.
    auteur_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    titre: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contenu: Mapped[str] = mapped_column(Text, nullable=False)
    echeance: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    #: Case cochée par le destinataire (ou l'auteur / un admin).
    fait: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        index=True,
    )
    fait_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Première ouverture par le destinataire ; NULL = « Nouveau ». Posé
    #: d'office à la création quand l'auteur écrit dans son propre bloc.
    lu_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
