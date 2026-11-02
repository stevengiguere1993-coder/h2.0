"""Défaut « à refacturer » d'un achat selon sa cible.

Règle (hook de création des achats, import des coûts QB, reçu divisé) :
refacturable par défaut UNIQUEMENT pour un projet à CONTRAT (coûtant
majoré) ou pour le mini-projet d'un BON DE TRAVAIL (temps & matériel).
Estimé, forfaitaire, sans soumission → NON refacturable : le prix donné
au client couvre les dépenses (cochable à la main ; un choix explicite de
l'utilisateur, ``billable_manual``, n'est jamais corrigé).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.soumission import Soumission


async def refacturable_par_defaut(
    db: AsyncSession, project_id: Optional[int]
) -> bool:
    """Vrai si un achat posé sur ce projet est refacturable par défaut :
    projet à contrat, ou mini-projet d'un bon de travail. Faux sans projet
    ou pour un projet estimé / forfaitaire / sans soumission."""
    if not project_id:
        return False
    row = (
        await db.execute(
            select(Project.soumission_id, Project.kind).where(
                Project.id == project_id
            )
        )
    ).first()
    if row is None:
        return False
    soumission_id, kind = row
    if (kind or "") == "bon_travail":
        return True
    if not soumission_id:
        return False
    soum_kind = (
        await db.execute(
            select(Soumission.kind).where(Soumission.id == soumission_id)
        )
    ).scalar_one_or_none()
    return soum_kind == "contract"
