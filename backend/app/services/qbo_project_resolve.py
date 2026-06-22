"""Résout le CustomerRef QB d'un projet Kratos, en tenant compte de la
CONVERSION des sous-clients en PROJETS dans QuickBooks.

Quand un sous-client créé par Kratos est converti en « Projet » dans QB,
l'ancien id (stocké dans `Project.qbo_job_id`) est SUPPRIMÉ et un nouvel
objet (le projet, lui-même un sous-client) est créé. Pousser une facture/
un coût avec l'ancien id échoue alors (« Le client saisi a été supprimé »).

Ce helper :
1. garde `qbo_job_id` s'il pointe encore sur un client ACTIF ;
2. sinon retrouve le sous-client/projet converti sous le parent (par nom /
   adresse) et met `qbo_job_id` à jour ;
3. à défaut, retombe sur le client PARENT (la classe = chantier assure
   quand même le suivi par projet).
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project

log = logging.getLogger(__name__)


async def _is_active_customer(qbo, cid: str) -> bool:
    try:
        rows = await qbo.query(
            f"SELECT Id FROM Customer WHERE Id = '{cid}' MAXRESULTS 1"
        )
        return bool(rows)
    except Exception:  # noqa: BLE001
        # En cas d'échec de la vérif, on suppose valide pour ne pas casser.
        return True


async def resolve_project_customer_id(
    qbo,
    db: AsyncSession,
    project: Project,
    parent_customer_id: str,
) -> str:
    """Retourne l'Id QB à utiliser comme CustomerRef pour ce projet, en
    réparant `qbo_job_id` si le sous-client a été converti en projet QB.
    Repli : client parent."""
    jid = (getattr(project, "qbo_job_id", None) or "").strip()
    if jid and await _is_active_customer(qbo, jid):
        return jid

    # Re-résolution : retrouver le sous-client / projet converti sous le
    # parent, par adresse (nom de migration) puis par nom de projet.
    for nm in (
        (getattr(project, "address", None) or "").strip(),
        (project.name or "").strip(),
    ):
        if not nm:
            continue
        try:
            sub = await qbo._find_subcustomer(
                parent_customer_id=parent_customer_id, project_name=nm
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("resolve job projet %s (%s): %s", project.id, nm, exc)
            sub = None
        if sub and sub.get("Id"):
            new_id = str(sub["Id"])
            if new_id != jid:
                project.qbo_job_id = new_id
                await db.flush()
            return new_id

    # Rien trouvé → parent (le projet reste suivi via la ClassRef).
    return str(parent_customer_id)
