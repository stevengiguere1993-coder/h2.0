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
3. sinon CRÉE le projet dans QB (API Projets si accordée, à défaut un
   sous-client convertible) — avant, on retombait silencieusement sur le
   client parent : la facture atterrissait sur le client, aucun
   sous-client « 29 Besner » n'existait, et rien n'était convertible en
   projet côté QB ;
4. en dernier recours, retombe sur le client PARENT (la classe =
   chantier assure quand même le suivi par projet).
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

    # Liste des sous-clients / projets sous le parent.
    try:
        subs = await qbo.find_subcustomers(parent_customer_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("find_subcustomers projet %s: %s", project.id, exc)
        subs = []

    def _local_name(row) -> str:
        fqn = row.get("FullyQualifiedName") or ""
        seg = fqn.split(":")[-1] if fqn else (row.get("DisplayName") or "")
        return seg.strip().lower()

    # Projet de BON DE TRAVAIL (kind="bon_travail") : le NOM porte le
    # numéro de bon (« BT-26-001 — … ») et doit primer sur l'adresse pour
    # nommer/retrouver le sous-client QB — demande : le sous-client du
    # client mère porte le n° de BT. Projets réguliers : adresse d'abord
    # (comportement historique).
    _prefer_name = (getattr(project, "kind", "") or "") == "bon_travail"
    _name_t = (project.name or "").strip().lower()
    _addr_t = (getattr(project, "address", None) or "").strip().lower()
    targets = [
        t
        for t in (
            (_name_t, _addr_t) if _prefer_name else (_addr_t, _name_t)
        )
        if t
    ]

    async def _adopt(row) -> str:
        new_id = str(row["Id"])
        if new_id != jid:
            project.qbo_job_id = new_id
            await db.flush()
        return new_id

    # 1) Match par NOM (adresse / nom de projet), tolérant aux renommages :
    # égalité, préfixe, ou inclusion (scopé au même parent → sûr).
    for row in subs:
        if not row.get("Id"):
            continue
        ln = _local_name(row)
        if not ln:
            continue
        for t in targets:
            if ln == t or ln.startswith(t) or t.startswith(ln) or t in ln or ln in t:
                return await _adopt(row)

    # 2) Un SEUL sous-client / projet sous ce parent → c'est forcément lui
    # (cas courant : 1 client = 1 projet), même s'il a été renommé.
    usable = [r for r in subs if r.get("Id")]
    if len(usable) == 1:
        return await _adopt(usable[0])

    # 3) Aucun sous-client → on CRÉE le projet QB (même logique que la
    # synchro en masse : nom = adresse du chantier, sinon nom du projet ;
    # bon de travail → NOM d'abord, il porte le n° de BT).
    if _prefer_name:
        project_name = (
            (project.name or "").strip()
            or (getattr(project, "address", None) or "").strip()
        )
    else:
        project_name = (
            (getattr(project, "address", None) or "").strip()
            or (project.name or "").strip()
        )
    if project_name:
        try:
            start = (
                project.created_at.date().isoformat()
                if getattr(project, "created_at", None)
                else None
            )
            job = await qbo.ensure_project(
                parent_customer_id=str(parent_customer_id),
                project_name=project_name,
                start_date=start,
            )
            new_id = str(job.get("Id") or "")
            if new_id:
                project.qbo_job_id = new_id
                await db.flush()
                return new_id
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Création du projet QB « %s » (projet %s) échouée : %s",
                project_name,
                project.id,
                exc,
            )

    # 4) Rien d'identifiable → client parent (suivi assuré par la ClassRef).
    return str(parent_customer_id)
