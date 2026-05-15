"""Besoin client (par pôle de dev) attaché à un lead Dev logiciel.

Une fiche prospect se documente par pôle (Frontend, Backend, Design,
DevOps/Hosting, Mobile, Intégrations, …). Chaque pôle est un
``DevlogLeadNeed`` avec sa note libre + indicateurs (complexité,
priorité). À partir des besoins, on peut :

  * générer un plan IA structuré (résumé exécutif + items par pôle) ;
  * créer automatiquement une soumission avec une section par pôle et
    des items pré-remplis (qté + coût interne estimés).
"""

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


# Pôles canoniques proposés à l'UI. La colonne accepte n'importe quelle
# chaîne — la liste sert seulement de défaut côté frontend pour pré-
# remplir des sections cohérentes (Frontend, Backend, ...).
NEED_POLES = (
    "frontend",
    "backend",
    "design",
    "devops",
    "hosting",
    "mobile",
    "integrations",
    "data",
    "ai",
    "autre",
)


class DevlogLeadNeed(Base, TimestampUpdateMixin):
    __tablename__ = "devlog_lead_needs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("devlog_leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Identifiant court du pôle (frontend, backend, ...). Libre — pas de
    # check pour permettre l'ajout de nouveaux pôles sans migration.
    pole: Mapped[str] = mapped_column(String(64), nullable=False)
    # Libellé affiché côté UI (ex. « Frontend », « Backend + API »).
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    # Note libre — description des besoins du client pour ce pôle.
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Indication de complexité (saisi par le closer) : simple / moyen /
    # complexe. Sert d'input à l'estimation IA.
    complexity: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )
    # Priorité (haut / moyen / bas) — utile pour ordonner les sections
    # dans la soumission générée.
    priority: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<DevlogLeadNeed(id={self.id}, lead_id={self.lead_id}, "
            f"pole='{self.pole}')>"
        )
