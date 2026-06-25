"""Correction automatique du défaut « à refacturer » des achats.

Règle métier (demandée par l'utilisateur) : une dépense rattachée à un
projet à CONTRAT (kind=contract, prix coûtant majoré) ou à un devis
ESTIMÉ (pricing_kind != forfaitaire) doit automatiquement apparaître
« À refacturer » dans la colonne REFACT — et y rester jusqu'à ce qu'elle
soit effectivement refacturée au client via Kratos (invoiced_at posé).

Concrètement, dans l'UI :
- is_billable == False           → « — » (pas de statut)
- is_billable == True, pas de    → « À refacturer »
  invoiced_at
- invoiced_at posé               → « ✓ Refacturé »

Certaines dépenses (saisie manuelle, import QB d'une facture déjà payée)
arrivent avec is_billable=False alors qu'elles sont sur un projet à
contrat. Ce service est un AUTOMATISME purement DB (aucun appel QB) qui
remet is_billable=True pour ces dépenses tant qu'elles ne sont pas encore
refacturées. Il NE touche JAMAIS une dépense déjà refacturée
(invoiced_at posé) ni une dépense d'un projet forfaitaire / sans
soumission.
"""

from __future__ import annotations

import logging

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.achat import Achat
from app.models.project import Project
from app.models.soumission import Soumission

log = logging.getLogger("app.achat_billable")


async def correct_billable_for_contract_projects(db: AsyncSession) -> int:
    """Passe is_billable=True sur les achats des projets refacturables.

    Renvoie le nombre de lignes corrigées. Idempotent : un second appel
    sans nouvelle dépense renvoie 0.
    """
    # Projets dont la soumission est refacturable. Aligné sur _is_billable
    # (qbo_cost_pull) et _billing_kind (endpoints/projects.py) : un CONTRAT
    # l'emporte, sinon tout pricing_kind != forfaitaire (estimé) est
    # refacturable.
    billable_project_ids = (
        select(Project.id)
        .join(Soumission, Soumission.id == Project.soumission_id)
        .where(
            or_(
                Soumission.kind == "contract",
                and_(
                    Soumission.pricing_kind.isnot(None),
                    Soumission.pricing_kind != "forfaitaire",
                ),
            )
        )
    )

    result = await db.execute(
        update(Achat)
        .where(
            Achat.project_id.in_(billable_project_ids),
            Achat.is_billable.is_(False),
            Achat.invoiced_at.is_(None),
        )
        .values(is_billable=True)
    )
    n = result.rowcount or 0
    if n:
        await db.commit()
        log.info("achat_billable_correct: %s dépense(s) → à refacturer", n)
    else:
        # Pas de COMMIT inutile, mais on referme la transaction implicite.
        await db.rollback()
    return n
