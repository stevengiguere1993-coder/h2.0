"""Partage contrôlé des codes d'accès (Steven 2026-11-13).

« Je ne peux pas donner accès au code à tous mes employés, par contre il
se pourrait que celui-ci en ait besoin pour répondre à un BT ou des
travaux […] le gestionnaire des projets a accès à la liste de codes, il
peut envoyer à un employé le code d'un endroit avec un nombre de jours
défini, ou le laisser accessible jusqu'à la fin d'un BT ou d'un projet. »

- ``ImmeubleCodePhoto`` : photos de l'emplacement d'un code (où est la
  boîte à clés, quelle porte).
- ``CodeAccesPartage`` : accès TEMPORAIRE d'un employé à un code, aux
  codes d'un logement (+ ceux de son immeuble) ou à tous les codes d'un
  immeuble ; fin à une date, à la fin d'un BT ou d'un projet. Les
  gestionnaires (manager+) voient tous les codes sans partage.
- ``CodeAccesConsultation`` : journal de chaque « Afficher le code ».

Logique dans ``app/services/codes_acces.py``. Nouvelles tables →
``ensure_immobilier_aux_tables``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class ImmeubleCodePhoto(Base):
    """Photo de l'endroit où se trouve le code (boîte à clés, porte…)."""

    __tablename__ = "imm_code_photos"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeuble_codes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    image: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=False)
    )
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    uploaded_by_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CodeAccesPartage(Base, TimestampUpdateMixin):
    """Accès temporaire d'un employé à des codes.

    Portée : ``code_id`` = ce code seulement ; sinon ``logement_id`` = les
    codes du logement ET ceux de son immeuble (on entre par la porte de
    l'immeuble) ; sinon tous les codes de l'immeuble.

    Fin (``mode``) : ``jours`` / ``date`` → ``fin_le`` ; ``bt`` → tant que
    le BT n'est pas terminé (signé, complété, facturé, annulé) ;
    ``projet`` → tant que le projet n'est pas livré. ``ferme_le`` est posé
    au retrait manuel ou par le filet horaire.
    """

    __tablename__ = "imm_code_partages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    immeuble_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeubles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    logement_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_logements.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    code_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_immeuble_codes.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    #: jours | date | bt | projet
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    fin_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bon_travail_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("bons_travail.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    motif: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    accorde_par_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    accorde_par_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    ferme_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    ferme_par_email: Mapped[Optional[str]] = mapped_column(
        String(320), nullable=True
    )
    #: retire | expire | fin_bt | fin_projet | compte_desactive | reassigne
    ferme_motif: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    #: Alerte « compte désactivé, penser à changer le code » déjà envoyée.
    alerte_compte_le: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CodeAccesConsultation(Base):
    """Une consultation d'un code (bouton « Afficher »)."""

    __tablename__ = "imm_code_consultations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code_id: Mapped[int] = mapped_column(
        ForeignKey("imm_immeuble_codes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    #: gestion (manager+) | partage (accès temporaire)
    via: Mapped[str] = mapped_column(String(16), nullable=False)
    partage_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("imm_code_partages.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
