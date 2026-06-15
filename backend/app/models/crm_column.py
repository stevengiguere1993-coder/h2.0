"""Colonnes personnalisées du tableau CRM (kanban prospects).

Avant, ces colonnes (ex. « À rappeler ») n'existaient que dans le
localStorage du navigateur, alors que la position de chaque prospect est
persistée en base (`contact_requests.kanban_column`). Résultat : sur un
autre appareil / après vidage du cache, la définition de colonne
disparaissait et les cartes « retombaient » dans leur colonne de statut
(« Nouveau »). On persiste donc la définition des colonnes ici, partagée
par toute l'équipe.
"""

from typing import Optional

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class CrmColumn(Base, TimestampUpdateMixin):
    __tablename__ = "crm_columns"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Clé stable référencée par contact_requests.kanban_column
    # (ex. « custom_1718481234567 »).
    key: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    # Classe Tailwind de la pastille de couleur (ex. « bg-sky-400 »).
    dot: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
