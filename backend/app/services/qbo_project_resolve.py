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
import re
import unicodedata
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project

log = logging.getLogger(__name__)

_SEP_RE = re.compile(r"[\s,;:·—–\-_/()\[\]#.'’«»\"|]+")


async def _customer_row(qbo, cid: str):
    """Lit le Customer QB ``cid`` (id échappé). Retourne le dict, None
    s'il n'existe plus (converti / supprimé), ou ``False`` si QB n'a pas
    répondu (on ne conclut rien : le lien est conservé tel quel)."""
    try:
        return await qbo.get_customer(str(cid).replace("'", "''"))
    except Exception:  # noqa: BLE001
        return False


async def _is_active_customer(qbo, cid: str) -> bool:
    row = await _customer_row(qbo, cid)
    return row is False or bool(row)


def _norm(value: Optional[str]) -> str:
    """Forme comparable d'un nom QB / d'une adresse Kratos : minuscules,
    sans accents, ponctuation et séparateurs (« , », « · », « — », « / »…)
    réduits à un espace. « 1616 Saint-Alexandre, Longueuil » et
    « 1616 saint alexandre longueuil » sont ainsi identiques."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return _SEP_RE.sub(" ", text.lower()).strip()


def _match_level(ln: str, t: str) -> int:
    """Niveau de correspondance entre un nom QB (``ln``) et une cible
    (``t``), tous deux normalisés : 3 = égalité ; 2 = l'un est le
    préfixe de l'autre à une frontière de mot (« 710 rue legendre est »
    vs « 710 rue legendre est app 1 ») ; 1 = inclusion à une frontière
    de mot (chaînes d'au moins 6 caractères, pour ignorer les noms
    génériques courts) ; 0 = rien. « 160 rue cadieux » n'est PAS inclus
    dans « 1160 rue cadieux » (pas de frontière de mot)."""
    if not ln or not t:
        return 0
    if ln == t:
        return 3
    if ln.startswith(t + " ") or t.startswith(ln + " "):
        return 2
    if len(ln) >= 6 and len(t) >= 6 and (
        f" {t} " in f" {ln} " or f" {ln} " in f" {t} "
    ):
        return 1
    return 0


def _best_level(ln: str, targets: list[str]) -> int:
    return max((_match_level(ln, t) for t in targets), default=0)


def _name_matches(ln: str, targets: list[str]) -> bool:
    """Égalité, préfixe ou inclusion à une frontière de mot."""
    return _best_level(ln, targets) > 0


def _project_targets(project: Project) -> list[str]:
    """Noms (normalisés) sous lesquels ce projet peut exister dans QB :
    adresse du chantier et nom du projet ; le nom d'abord pour un bon de
    travail car il porte le n° de BT."""
    return _targets_of(
        getattr(project, "kind", None), getattr(project, "address", None),
        project.name,
    )


def _targets_of(kind: Optional[str], address: Optional[str], name: Optional[str]) -> list[str]:
    """Cibles d'un projet : adresse puis nom pour un projet régulier ;
    pour un BON DE TRAVAIL, le NOM seulement (il porte le n° de BT),
    l'adresse n'étant qu'un repli si le nom est vide — sinon un bon à
    l'adresse d'un chantier régulier adopterait le sous-client de ce
    chantier (audit 2026-09-21)."""
    n, a = _norm(name), _norm(address)
    if (kind or "") == "bon_travail":
        return [t for t in (n or a,) if t]
    return [t for t in (a, n) if t]


def _primary_target(kind: Optional[str], address: Optional[str], name: Optional[str]) -> str:
    """Cible PRINCIPALE d'un projet frère : son adresse (nom à défaut)
    pour un projet régulier, son nom (adresse à défaut) pour un bon de
    travail. On ne compare pas aux noms génériques des projets réguliers
    (« Toiture », « Cuisine ») : ils feraient des faux positifs."""
    if (kind or "") == "bon_travail":
        return _norm(name) or _norm(address)
    return _norm(address) or _norm(name)


async def _other_projects_targets(
    db: AsyncSession, project: Project
) -> list[str]:
    """Cibles principales des AUTRES projets Kratos du même client : un
    sous-client QB qui porte l'une d'elles appartient à cet autre
    chantier, jamais à celui-ci (retour 2026-09-21 : le 1616
    Saint-Alexandre s'était fait relier au sous-client du 1160 Cadieux,
    même client)."""
    if not getattr(project, "client_id", None):
        return []
    try:
        rows = (
            await db.execute(
                select(Project.kind, Project.address, Project.name).where(
                    Project.client_id == project.client_id,
                    Project.id != project.id,
                )
            )
        ).all()
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for kind, addr, name in rows:
        t = _primary_target(kind, addr, name)
        if t:
            out.append(t)
    return out


async def _links_of_other_projects(
    db: AsyncSession, project: Project
) -> dict[str, tuple[int, list[str]]]:
    """Ids QB portés par d'AUTRES projets Kratos → (id du projet porteur,
    ses cibles normalisées). Sert à ne jamais adopter le sous-client d'un
    autre chantier — et, symétriquement, à reconnaître qu'un lien porté
    par un autre projet est ERRONÉ quand le nom QB ne lui correspond pas
    mais correspond exactement à celui-ci (retour 2026-09-21)."""
    try:
        rows = (
            await db.execute(
                select(
                    Project.id, Project.qbo_job_id, Project.kind,
                    Project.address, Project.name,
                ).where(
                    Project.id != project.id,
                    Project.qbo_job_id.is_not(None),
                )
            )
        ).all()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, tuple[int, list[str]]] = {}
    for pid, jid, kind, addr, name in rows:
        jid = (jid or "").strip()
        if not jid:
            continue
        out[jid] = (int(pid), _targets_of(kind, addr, name))
    return out


async def _job_ids_used_by_other_projects(
    db: AsyncSession, project: Project
) -> set[str]:
    return set((await _links_of_other_projects(db, project)).keys())


async def _lien_errone(
    db: AsyncSession,
    project: Project,
    jid: str,
    row: dict,
    *,
    parent_customer_id: str,
    links: dict[str, tuple[int, list[str]]],
    others: list[str],
) -> bool:
    """Vrai si le sous-client QB actuellement lié appartient visiblement
    à un AUTRE chantier :
    - il est sous un AUTRE client mère que celui du projet (projet
      rattaché à un nouveau client) ;
    - porté aussi par un autre projet Kratos → le garde celui dont le nom
      QB correspond le mieux ; à égalité (deux projets à la MÊME
      adresse), le plus ancien (id le plus petit) le garde ;
    - sinon, son nom correspond MIEUX (égalité ou préfixe, jamais une
      simple inclusion) à un autre projet du même client qu'à celui-ci
      (ex. « 710 rue legendre est » lié au projet « … · App 1 » alors que
      le projet « 710 rue legendre est » existe).
    Un simple renommage côté QB sans conflit ne compte pas comme erreur."""
    parent_of_row = str((row.get("ParentRef") or {}).get("value") or "")
    if parent_of_row and parent_of_row != str(parent_customer_id):
        return True
    ln = _norm(_local_name_of(row))
    mine = _best_level(ln, _project_targets(project))
    held = links.get(jid)
    if held is not None:
        holder_id, holder_targets = held
        theirs = _best_level(ln, holder_targets)
        if mine > theirs:
            return False
        if mine < theirs:
            return True
        return int(project.id) > holder_id
    if mine == 3:
        return False
    sib = _best_level(ln, others)
    return sib >= 2 and sib > mine


def _local_name_of(row) -> str:
    fqn = row.get("FullyQualifiedName") or ""
    seg = fqn.split(":")[-1] if fqn else (row.get("DisplayName") or "")
    return seg.strip()


def _is_duplicate_name_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "6240" in msg or "duplicate" in msg or "already exists" in msg or "existe" in msg


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

    links = await _links_of_other_projects(db, project)
    others = await _other_projects_targets(db, project)

    jid = (getattr(project, "qbo_job_id", None) or "").strip()
    if jid == str(parent_customer_id):
        # Lié au client MÈRE lui-même (ancien repli mémorisé, liaison
        # manuelle) : ce n'est pas un sous-client → on repart.
        jid = ""
    if jid:
        row = await _customer_row(qbo, jid)
        if row is False:
            # QB injoignable : on ne conclut rien, on garde le lien.
            _note("deja_lie")
            return jid
        if row and not await _lien_errone(
            db, project, jid, row,
            parent_customer_id=str(parent_customer_id),
            links=links, others=others,
        ):
            _note("deja_lie")
            return jid
        if row:
            log.warning(
                "Projet %s « %s » : le sous-client QB lié (%s) appartient à "
                "un autre chantier ou client — lien oublié, on repart de "
                "l'adresse.", project.id, project.name, jid,
            )
        project.qbo_job_id = None
        await db.flush()
        jid = ""

    # Liste des sous-clients / projets sous le parent.
    try:
        subs = await qbo.find_subcustomers(parent_customer_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("find_subcustomers projet %s: %s", project.id, exc)
        subs = []

    def _local_name(row) -> str:
        return _norm(_local_name_of(row))

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

    # Tri des sous-clients du parent :
    # - porté par un autre projet Kratos dont le nom QB correspond → à lui
    #   (exclu) ; porté par un autre projet mais le nom correspond
    #   EXACTEMENT à celui-ci et pas au porteur → lien erroné chez
    #   l'autre : on l'adopte ET on délie l'autre (symétrique de
    #   _lien_errone) ;
    # - un nom qui correspond exactement à ce projet est toujours à lui ;
    # - une correspondance seulement tolérante (préfixe / inclusion) n'est
    #   acceptée que si AUCUN autre projet du client ne correspond aussi
    #   (« 710 rue legendre est » n'est pas adopté par « … · App 1 »).
    candidates: list[tuple[int, dict]] = []
    taken_names: set[str] = set()
    to_unlink: dict[str, int] = {}
    for row in subs:
        rid = str(row.get("Id") or "")
        if not rid:
            continue
        ln = _local_name(row)
        mine = _best_level(ln, targets)
        held = links.get(rid)
        if held is not None:
            holder_id, holder_targets = held
            theirs = _best_level(ln, holder_targets)
            if not (mine > theirs and mine >= 2):
                taken_names.add(ln)
                continue
            to_unlink[rid] = holder_id
        if mine == 0:
            continue
        if mine < 3 and _best_level(ln, others) >= mine:
            continue
        candidates.append((mine, row))

    # 1) Meilleure correspondance de NOM (adresse / nom de projet).
    if candidates:
        candidates.sort(key=lambda c: -c[0])
        best_level, best = candidates[0]
        rid = str(best["Id"])
        if rid in to_unlink:
            holder_id = to_unlink[rid]
            log.warning(
                "Projet %s « %s » : le sous-client QB %s (« %s ») était "
                "porté à tort par le projet %s — lien transféré.",
                project.id, project.name, rid, _local_name_of(best), holder_id,
            )
            await db.execute(
                update(Project)
                .where(Project.id == holder_id, Project.qbo_job_id == rid)
                .values(qbo_job_id=None)
            )
            if report is not None:
                report["transfere_de"] = holder_id
        return await _adopt(best)

    # 2) Un SEUL sous-client / projet sous ce parent → c'est forcément lui,
    # même s'il a été renommé — UNIQUEMENT si ce projet est le seul projet
    # Kratos de ce client (l'hypothèse « 1 client = 1 projet » de la règle
    # doit être vraie). Un client à plusieurs chantiers n'adopte que par
    # correspondance de nom/adresse : chaque chantier a son sous-client.
    usable = [
        r for r in subs
        if r.get("Id") and str(r["Id"]) not in links
    ]
    if len(usable) == 1 and not others:
        return await _adopt(usable[0])

    # 3) Aucun sous-client → on CRÉE le projet QB (même logique que la
    # synchro en masse : nom = adresse du chantier, sinon nom du projet ;
    # bon de travail → NOM d'abord, il porte le n° de BT). Si ce nom est
    # déjà porté par le sous-client d'un AUTRE projet du client (deux
    # chantiers à la même adresse) ou refusé par QB (nom en double —
    # DisplayName est unique dans toute la compagnie), on dérive un nom
    # distinctif : « adresse — nom du projet », puis « adresse (#id) ».
    if _prefer_name:
        base = (
            (project.name or "").strip()
            or (getattr(project, "address", None) or "").strip()
        )
    else:
        base = (
            (getattr(project, "address", None) or "").strip()
            or (project.name or "").strip()
        )
    if base:
        # DisplayName QB ≤ 100 caractères : le suffixe distinctif doit
        # SURVIVRE à la troncature, sinon les variantes se confondent.
        def _with_suffix(suffix: str) -> str:
            keep = max(1, 100 - len(suffix))
            return base[:keep].rstrip() + suffix

        variants: list[str] = [base[:100].rstrip()]
        pname = (project.name or "").strip()
        if pname and _norm(pname) != _norm(base):
            variants.append(_with_suffix(f" — {pname}"[:40]))
        variants.append(_with_suffix(f" (#{project.id})"))
        variants = list(dict.fromkeys(v for v in variants if v))
        existing_ids = {str(r.get("Id") or "") for r in subs}
        start = (
            project.created_at.date().isoformat()
            if getattr(project, "created_at", None)
            else None
        )
        for name in variants:
            if _norm(name) in taken_names:
                continue
            try:
                job = await qbo.ensure_project(
                    parent_customer_id=str(parent_customer_id),
                    project_name=name,
                    start_date=start,
                )
            except Exception as exc:  # noqa: BLE001
                if _is_duplicate_name_error(exc):
                    log.info(
                        "Projet %s : nom QB « %s » déjà pris, essai du "
                        "suivant.", project.id, name,
                    )
                    continue
                log.warning(
                    "Création du projet QB « %s » (projet %s) échouée : %s",
                    name, project.id, exc,
                )
                break
            new_id = str(job.get("Id") or "")
            if not new_id:
                break
            if new_id in links:
                # ensure_project a retrouvé par nom exact le sous-client
                # d'un autre projet : jamais — on passe au nom suivant.
                continue
            project.qbo_job_id = new_id
            await db.flush()
            _note("adopte" if new_id in existing_ids else "cree")
            return new_id

    # 4) Rien d'identifiable → client parent (suivi assuré par la ClassRef).
    _note("parent")
    return str(parent_customer_id)
