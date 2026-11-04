"""Scénarios « Revenus et dépenses » de la société de gestion (Gestion
d'entreprise, 2026-11-04). Un scénario = un JSON d'hypothèses (mode
simulation) + un résumé des résultats calculés. Nouvelle table →
create_all au démarrage (ensure_critical_columns) ; exposée à l'API IA /
MCP (liste « simulations_revenus_depenses », détail « rd_scenario »)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RdScenario(Base):
    __tablename__ = "rd_scenarios"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nom: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Hypothèses (voir services/revenus_depenses.normaliser).
    data_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    #: Résumé des résultats au dernier enregistrement (revenus, dépenses,
    #: bénéfice, marge, dividendes, VAN nécessaire).
    resume_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_by_email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
