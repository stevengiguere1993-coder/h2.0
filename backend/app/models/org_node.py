"""Organigramme : structure arborescente des départements / rôles /
services partagés du groupe. Inspirée du schéma papier de Steven :

  Business
    ├── Construction (MV)         → Chargé Projet, Closer, Sous-traitant
    ├── Dev logiciel (Phil)       → Développeur, Acquisition, Payable, Recevable
    ├── Gestion Immo (Steven)     → Kyle/Kario, Communication, Gestion loyers, ...
    ├── Prospection (Steven)      → Prospecteur (Zach), Acquisition, ...
    └── Dev Immo / Aguci (Inc)    → Dev logiciel, Dev prospection, ...

Chaque nœud peut être :
  - kind="dept" — une grande branche (Construction, Gestion Immo...)
  - kind="role" — un poste / responsabilité (Chargé Projet, Développeur...)
  - kind="service" — un service partagé (Comptabilité, Gestion taxes...)
  - kind="task" — une tâche concrète sous un rôle

Chaque nœud peut être assigné à :
  - un employé interne (assignee_employe_id)
  - un user du portail (assignee_user_id)
  - un externe avec label libre (assignee_external_name) — ex.
    "Freelance Phil", "Sous-traitant XYZ"

Chaque nœud peut être lié à une entreprise spécifique
(entreprise_id), ou être transverse (null = appartient au groupe).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class OrgNode(Base, TimestampUpdateMixin):
    __tablename__ = "org_nodes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Hiérarchie : nœud parent ou racine (NULL = top-level).
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("org_nodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Ordre dans la liste des enfants du parent (drag-and-drop).
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Nature du nœud (dept | role | service | task).
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="dept", server_default="dept",
        index=True,
    )

    # Label affiché (ex. "Construction", "Chargé Projet", "Gestion taxes").
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Entreprise concernée (NULL = transverse / niveau groupe).
    entreprise_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("entreprises.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Assignation : un seul des 3 champs est utilisé selon le type
    # de personne responsable.
    assignee_employe_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employes.id", ondelete="SET NULL"), nullable=True
    )
    assignee_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Pour les externes (freelance, sous-traitant, partenaire) on
    # garde juste un texte libre — pas la peine de créer un employé.
    assignee_external_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
