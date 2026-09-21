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

from sqlalchemy import select
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


async def _job_ids_used_by_other_projects(
    db: AsyncSession, project: Project
) -> set[str]:
    """Ids QB déjà portés par d'AUTRES projets Kratos : on ne les adopte
    jamais (retour 2026-09-21 : sinon un second projet du même client
    « prenait » le sous-client du premier et n'apparaissait jamais dans
    QuickBooks sous son propre nom)."""
    try:
        rows = (
            await db.execute(
                select(Project.qbo_job_id).where(
                    Project.id != project.id,
                    Project.qbo_job_id.is_not(None),
                )
            )
        ).scalars().all()
        return {str(r).strip() for r in rows if r}
    except Exception:  # noqa: BLE001
        return set()


def _project_targets(project: Project) -> list[str]:
    """Noms sous lesquels ce projet peut exister dans QB (adresse du
    chantier et nom du projet, en minuscules ; le nom d'abord pour un
    bon de travail car il porte le n° de BT)."""
    _prefer_name = (getattr(project, "kind", "") or "") == "bon_travail"
    _name_t = (project.name or "").strip().lower()
    _addr_t = (getattr(project, "address", None) or "").strip().lower()
    return [
        t
        for t in ((_name_t, _addr_t) if _prefer_name else (_addr_t, _name_t))
        if t
    ]


def _name_matches(ln: str, targets: list[str]) -> bool:
    """Égalité, préfixe ou inclusion (tolérant aux renommages légers)."""
    for t in targets:
        if not t:
            continue
        if ln == t or ln.startswith(t) or t.startswith(ln) or t in ln or ln in t:
            return True
    return False


async def _other_projects_targets(
    db: AsyncSession, project: Project
) -> list[str]:
    """Adresses / noms des AUTRES projets Kratos du même client : un
    sous-client QB qui porte l'un d'eux appartient à cet autre chantier,
    jamais à celui-ci (retour 2026-09-21 : le 1616 Saint-Alexandre
    s'était fait relier au sous-client du 1160 Cadieux, même client)."""
    if not getattr(project, "client_id", None):
        return []
    try:
        rows = (
            await db.execute(
                select(Project.address, Project.name).where(
                    Project.client_id == project.client_id,
                    Project.id != project.id,
                )
            )
        ).all()
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for addr, name in rows:
        for t in ((addr or "").strip().lower(), (name or "").strip().lower()):
            if t:
                out.append(t)
    return out


async def _lien_errone(
    qbo, db: AsyncSession, project: Project, jid: str
) -> bool:
    """Vrai si le sous-client QB actuellement lié appartient visiblement
    à un AUTRE chantier : son nom ne correspond pas à ce projet ET
    (il correspond à un autre projet Kratos du même client, ou un autre
    projet Kratos porte déjà cet id). Un simple renommage côté QB (sans
    conflit) ne compte pas comme erreur."""
    try:
        row = await qbo.get_customer(jid)
    except Exception:  # noqa: BLE001
        return False
    if not row:
        return False
    fqn = row.get("FullyQualifiedName") or ""
    ln = (fqn.split(":")[-1] if fqn else (row.get("DisplayName") or "")).strip().lower()
    if not ln or _name_matches(ln, _project_targets(project)):
        return False
    if jid in await _job_ids_used_by_other_projects(db, project):
        return True
    return _name_matches(ln, await _other_projects_targets(db, project))


async def resolve_project_customer_id(
    qbo,
    db: AsyncSession,
    project: Project,
    parent_customer_id: str,
    report: Optional[dict] = None,
) -> str:
    """Retourne l'Id QB à utiliser comme CustomerRef pour ce projet, en
    réparant `qbo_job_id` si le sous-client a été converti en projet QB.
    Repli : client parent. ``report`` (optionnel) reçoit ``action`` :
    ``deja_lie`` | ``adopte`` | ``cree`` | ``parent``."""
    def _note(action: str) -> None:
        if report is not None:
            report["action"] = action

    jid = (getattr(project, "qbo_job_id", None) or "").strip()
    if jid and await _is_active_customer(qbo, jid):
        if not await _lien_errone(qbo, db, project, jid):
            _note("deja_lie")
            return jid
        log.warning(
            "Projet %s « %s » : le sous-client QB lié (%s) appartient à un "
            "autre chantier — lien oublié, on repart de l'adresse.",
            project.id, project.name, jid,
        )
        project.qbo_job_id = None
        await db.flush()
        jid = ""

    taken = await _job_ids_used_by_other_projects(db, project)
    others = await _other_projects_targets(db, project)

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
    targets = _project_targets(project)

    async def _adopt(row) -> str:
        new_id = str(row["Id"])
        if new_id != jid:
            project.qbo_job_id = new_id
            await db.flush()
        _note("adopte")
        return new_id

    # Jamais adopter un sous-client déjà lié à un autre projet Kratos, ni
    # un sous-client qui porte l'adresse / le nom d'un autre chantier du
    # même client (il est à lui, même s'il n'est pas encore relié).
    subs = [
        r
        for r in subs
        if str(r.get("Id") or "") not in taken
        and not (
            _local_name(r)
            and not _name_matches(_local_name(r), targets)
            and _name_matches(_local_name(r), others)
        )
    ]

    # 1) Match par NOM (adresse / nom de projet), tolérant aux renommages :
    # égalité, préfixe, ou inclusion (scopé au même parent → sûr).
    for row in subs:
        if not row.get("Id"):
            continue
        ln = _local_name(row)
        if not ln:
            continue
        if _name_matches(ln, targets):
            return await _adopt(row)

    # 2) Un SEUL sous-client / projet sous ce parent → c'est forcément lui,
    # même s'il a été renommé — UNIQUEMENT si ce projet est le seul projet
    # Kratos de ce client (l'hypothèse « 1 client = 1 projet » de la règle
    # doit être vraie). Un client à plusieurs chantiers n'adopte que par
    # correspondance de nom/adresse : chaque chantier a son sous-client.
    usable = [r for r in subs if r.get("Id")]
    if len(usable) == 1 and not others:
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
                _note("cree")
                return new_id
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Création du projet QB « %s » (projet %s) échouée : %s",
                project_name,
                project.id,
                exc,
            )

    # 4) Rien d'identifiable → client parent (suivi assuré par la ClassRef).
    _note("parent")
    return str(parent_customer_id)
