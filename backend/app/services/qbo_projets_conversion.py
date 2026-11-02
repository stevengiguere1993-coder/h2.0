"""Sous-clients QuickBooks à convertir en PROJETS (Steven, 2026-10-14).

Intuit ne laisse créer un projet QuickBooks par API qu'à ses partenaires
payants (API Projets, palier Silver et plus) ; Steven ne prend pas Silver.
L'API comptable v3, elle, ne sait que LIRE ``Customer.IsProject``. Kratos
continue donc de créer le SOUS-CLIENT sous le client mère (déjà le cas) et
tient la liste de ceux qu'il reste à convertir :

- l'extension Chrome « Horizon h2.0 Helper » (``browser-extension/
  content-qbo.js``) lit cette liste et fait la conversion dans le
  QuickBooks ouvert de la technicienne (Projets → Nouveau projet ▾ →
  Convertir depuis un sous-client), avec sa session à elle : aucun mot de
  passe QuickBooks dans Kratos ;
- Kratos CONSTATE la conversion par l'API (``IsProject``), que l'extension
  ou une personne l'ait faite, et raye la ligne. Après la conversion, QB
  remplace souvent le sous-client par un nouvel objet (ancien id
  supprimé) : on relie alors le projet au nouveau par son nom, comme le
  fait ``qbo_project_resolve`` — mais SANS rien créer : une vérification
  ne touche pas à QuickBooks.

État sur le projet (``Project.qbo_conversion_etat``) : NULL = rien à
faire (projet d'avant cette fonction, ou sans sous-client), puis
« a_convertir », « convertie » ou « ignoree ». Seuls les sous-clients
créés À PARTIR DE MAINTENANT entrent dans la liste ; les projets existants
s'y ajoutent sur demande (« Ajouter les projets existants »).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.client import Client
from app.models.project import Project
from app.models.qbo_token import QboToken

log = logging.getLogger(__name__)

A_CONVERTIR = "a_convertir"
CONVERTIE = "convertie"
IGNOREE = "ignoree"

#: Conversions récentes montrées sous la liste (jours).
CONVERTIES_RECENTES_JOURS = 30


class ConversionErreur(Exception):
    """Erreur présentable telle quelle (QuickBooks non connecté…)."""

    def __init__(self, message: str, statut: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.statut = statut


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────────────
# Marquage
# ──────────────────────────────────────────────────────────────────────


def nom_sous_client(row: Optional[Dict[str, Any]]) -> Optional[str]:
    """Nom d'affichage du sous-client (celui de la liste « Convertir
    depuis un sous-client » de QB) ; repli sur le dernier segment du nom
    complet « Client:Sous-client »."""
    if not row:
        return None
    nom = (row.get("DisplayName") or "").strip()
    if not nom:
        fqn = row.get("FullyQualifiedName") or ""
        nom = fqn.split(":")[-1].strip()
    return nom or None


def demander(project: Project, row: Optional[Dict[str, Any]] = None) -> None:
    """Met le projet dans la liste à convertir (sous-client qui vient
    d'être créé ou adopté). Un projet déjà converti ou ignoré n'y revient
    pas ; un sous-client qui est déjà un projet est noté converti."""
    if row is not None:
        project.qbo_job_name = nom_sous_client(row) or project.qbo_job_name
    if project.qbo_conversion_etat in (CONVERTIE, IGNOREE):
        return
    if row is not None and row.get("IsProject"):
        _marquer_convertie(project, row)
        return
    if project.qbo_conversion_etat != A_CONVERTIR:
        project.qbo_conversion_etat = A_CONVERTIR
        project.qbo_conversion_detail = None


def _marquer_convertie(project: Project, row: Dict[str, Any]) -> None:
    project.qbo_job_name = nom_sous_client(row) or project.qbo_job_name
    if project.qbo_conversion_etat != CONVERTIE:
        project.qbo_conversion_etat = CONVERTIE
        project.qbo_conversion_le = _maintenant()
        project.qbo_conversion_detail = None


def ignorer(project: Project) -> None:
    project.qbo_conversion_etat = IGNOREE
    project.qbo_conversion_detail = None


def reprendre(project: Project) -> None:
    project.qbo_conversion_etat = A_CONVERTIR
    project.qbo_conversion_detail = None


# ──────────────────────────────────────────────────────────────────────
# QuickBooks (compagnie Construction : c'est elle qui porte les projets)
# ──────────────────────────────────────────────────────────────────────


def lien_projets_qb(environment: Optional[str], realm_id: Optional[str]) -> str:
    """Page Projets de QuickBooks, ouverte sur la bonne compagnie."""
    hote = (
        "https://app.sandbox.qbo.intuit.com"
        if (environment or "").lower() == "sandbox"
        else "https://app.qbo.intuit.com"
    )
    url = f"{hote}/app/projects"
    if realm_id:
        url += f"?deeplinkcompanyid={realm_id}"
    return url


async def etat_quickbooks(db: AsyncSession) -> Dict[str, Any]:
    tok = (await db.execute(select(QboToken).where(QboToken.id == 1))).scalar_one_or_none()
    env = (tok.environment if tok else None) or settings.quickbooks_env
    realm = tok.realm_id if tok else None
    return {
        "connectee": bool(tok and tok.refresh_token and tok.realm_id),
        "company_name": (tok.company_name if tok else None) or "Horizon (Construction)",
        "realm_id": realm,
        "environment": env,
        "lien_projets": lien_projets_qb(env, realm),
    }


async def _qbo() -> Any:
    from app.integrations.quickbooks import get_qbo

    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        raise ConversionErreur(
            "QuickBooks (Construction) n'est pas connecté à Kratos : reconnecte-le "
            "dans Paramètres → Comptabilité."
        )
    return qbo


async def _clients_qb(qbo: Any) -> Dict[str, Dict[str, Any]]:
    """Tous les clients ACTIFS de la compagnie, par Id : un sous-client
    converti n'a plus le même id, et le projet qui le remplace n'est pas
    forcément « Job = true » → on lit tout, une seule fois."""
    from app.integrations.quickbooks import QuickBooksError

    try:
        rows = await qbo.query_all("SELECT * FROM Customer")
    except QuickBooksError as exc:
        raise ConversionErreur(f"QuickBooks ne répond pas : {str(exc)[:200]}", 502) from exc
    return {str(r.get("Id")): r for r in rows if r.get("Id")}


# ──────────────────────────────────────────────────────────────────────
# Vérification (constat par l'API, sans rien créer dans QuickBooks)
# ──────────────────────────────────────────────────────────────────────


def _parent_qb(
    client: Optional[Client], clients: Dict[str, Dict[str, Any]]
) -> Optional[str]:
    """Id QB du client mère : le lien de la fiche, sinon le client de
    premier niveau qui porte exactement son nom."""
    if client is None:
        return None
    if client.qbo_customer_id and str(client.qbo_customer_id) in clients:
        return str(client.qbo_customer_id)
    voulu = (client.name or "").strip().lower()
    if not voulu:
        return None
    for cid, row in clients.items():
        if (row.get("ParentRef") or {}).get("value"):
            continue
        if (row.get("DisplayName") or "").strip().lower() == voulu:
            return cid
    return None


def _retrouver(
    project: Project, parent: str, clients: Dict[str, Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Le sous-client / projet de ce projet Kratos sous le client mère,
    par son nom (celui mémorisé, sinon l'adresse / le nom du projet).
    Un projet QB (IsProject) passe avant un simple sous-client."""
    from app.services.qbo_project_resolve import (
        _best_level,
        _local_name_of,
        _norm,
        _project_targets,
    )

    cibles = [t for t in (_norm(project.qbo_job_name),) if t]
    cibles += [t for t in _project_targets(project) if t not in cibles]
    meilleur: Tuple[int, int, Optional[Dict[str, Any]]] = (0, 0, None)
    for row in clients.values():
        if str((row.get("ParentRef") or {}).get("value") or "") != str(parent):
            continue
        niveau = _best_level(_norm(_local_name_of(row)), cibles)
        if niveau < 2:
            continue
        cle = (niveau, 1 if row.get("IsProject") else 0)
        if cle > meilleur[:2]:
            meilleur = (cle[0], cle[1], row)
    return meilleur[2]


async def _verifier_un(
    db: AsyncSession, project: Project, clients: Dict[str, Dict[str, Any]]
) -> str:
    """Constate l'état QB du sous-client du projet et le note. Retourne
    l'état résultant (« convertie » ou l'état inchangé)."""
    jid = (project.qbo_job_id or "").strip()
    row = clients.get(jid) if jid else None
    if row is None:
        # Sous-client absent : QB l'a remplacé par le projet (conversion
        # faite), ou il n'a jamais existé. On cherche le projet / le
        # sous-client sous le client mère, par son nom.
        client = await db.get(Client, project.client_id) if project.client_id else None
        parent = _parent_qb(client, clients)
        if parent:
            row = _retrouver(project, parent, clients)
            if row is not None and str(row.get("Id")) != jid:
                project.qbo_job_id = str(row.get("Id"))
        if row is None:
            if project.qbo_conversion_etat == A_CONVERTIR:
                project.qbo_conversion_detail = (
                    "Sous-client introuvable dans QuickBooks : relance « Créer dans "
                    "QuickBooks » sur la fiche du projet."
                )
            return project.qbo_conversion_etat or ""
    if row.get("IsProject"):
        _marquer_convertie(project, row)
        return CONVERTIE
    project.qbo_job_name = nom_sous_client(row) or project.qbo_job_name
    return project.qbo_conversion_etat or ""


async def verifier(
    db: AsyncSession, *, projets: Optional[List[Project]] = None
) -> Dict[str, Any]:
    """Relit QuickBooks pour les projets « à convertir » (ou ceux donnés) :
    ceux dont le sous-client est devenu un projet passent « convertie »."""
    if projets is None:
        projets = list(
            (
                await db.execute(
                    select(Project).where(Project.qbo_conversion_etat == A_CONVERTIR)
                )
            ).scalars().all()
        )
    if not projets:
        return {"verifies": 0, "converties": [], "restantes": []}
    qbo = await _qbo()
    clients = await _clients_qb(qbo)
    converties: List[int] = []
    restantes: List[int] = []
    for p in projets:
        etat = await _verifier_un(db, p, clients)
        (converties if etat == CONVERTIE else restantes).append(p.id)
    await db.flush()
    return {"verifies": len(projets), "converties": converties, "restantes": restantes}


async def verifier_pour_cron(db: AsyncSession) -> Dict[str, Any]:
    """Passage quotidien : raye ce qui a été converti (extension ou à la
    main). Rien à faire sans projet en attente ou sans QuickBooks."""
    try:
        return await verifier(db)
    except ConversionErreur as exc:
        return {"skipped": exc.message}


async def ajouter_existants(db: AsyncSession) -> Dict[str, Any]:
    """Sur demande : met dans la liste les projets d'AVANT cette fonction
    (état vide) dont le sous-client QB n'est pas encore un projet ; ceux
    déjà convertis sont notés tels quels."""
    projets = list(
        (
            await db.execute(
                select(Project).where(
                    Project.qbo_job_id.is_not(None),
                    Project.qbo_conversion_etat.is_(None),
                )
            )
        ).scalars().all()
    )
    if not projets:
        return {"ajoutes": 0, "deja_converties": 0}
    qbo = await _qbo()
    clients = await _clients_qb(qbo)
    ajoutes = deja = 0
    for p in projets:
        row = clients.get(str(p.qbo_job_id))
        if row is None or not (row.get("ParentRef") or {}).get("value"):
            continue  # sous-client disparu, ou lié au client mère : rien à convertir
        if row.get("IsProject"):
            _marquer_convertie(p, row)
            deja += 1
        else:
            p.qbo_job_name = nom_sous_client(row) or p.qbo_job_name
            p.qbo_conversion_etat = A_CONVERTIR
            p.qbo_conversion_detail = "Projet existant, ajouté à la demande."
            ajoutes += 1
    await db.flush()
    return {"ajoutes": ajoutes, "deja_converties": deja}


# ──────────────────────────────────────────────────────────────────────
# Listes (page Comptabilité → Projets QB, extension)
# ──────────────────────────────────────────────────────────────────────


async def _noms_clients(db: AsyncSession, projets: List[Project]) -> Dict[int, str]:
    ids = sorted({p.client_id for p in projets if p.client_id})
    if not ids:
        return {}
    rows = (await db.execute(select(Client.id, Client.name).where(Client.id.in_(ids)))).all()
    return {cid: (nom or "").strip() for cid, nom in rows}


def _nom_qb(project: Project) -> str:
    """Nom du sous-client tel que créé par Kratos : nom QB mémorisé, sinon
    la convention (adresse du chantier ; nom pour un bon de travail)."""
    if project.qbo_job_name:
        return project.qbo_job_name
    if (project.kind or "") == "bon_travail":
        return (project.name or project.address or "").strip()
    return (project.address or project.name or "").strip()


def _ligne(project: Project, clients: Dict[int, str]) -> Dict[str, Any]:
    client = clients.get(project.client_id or 0, "")
    nom = _nom_qb(project)
    return {
        "project_id": project.id,
        "projet": project.name,
        "kind": project.kind,
        "client": client or None,
        "sous_client": nom,
        "sous_client_complet": f"{client}:{nom}" if client else nom,
        "etat": project.qbo_conversion_etat,
        "detail": project.qbo_conversion_detail,
        "convertie_le": project.qbo_conversion_le.isoformat() if project.qbo_conversion_le else None,
        "cree_le": project.created_at.isoformat() if project.created_at else None,
    }


async def liste(db: AsyncSession) -> Dict[str, Any]:
    projets = list(
        (
            await db.execute(
                select(Project)
                .where(Project.qbo_conversion_etat.is_not(None))
                .order_by(Project.created_at.desc(), Project.id.desc())
            )
        ).scalars().all()
    )
    noms = await _noms_clients(db, projets)
    recent = _maintenant().timestamp() - CONVERTIES_RECENTES_JOURS * 86400
    a_convertir, converties, ignorees = [], [], []
    for p in projets:
        ligne = _ligne(p, noms)
        if p.qbo_conversion_etat == A_CONVERTIR:
            a_convertir.append(ligne)
        elif p.qbo_conversion_etat == IGNOREE:
            ignorees.append(ligne)
        elif p.qbo_conversion_etat == CONVERTIE:
            le = p.qbo_conversion_le
            if le is None or le.timestamp() >= recent:
                converties.append(ligne)
    return {
        "quickbooks": await etat_quickbooks(db),
        "a_convertir": a_convertir,
        "converties": converties,
        "ignorees": ignorees,
    }


async def pour_extension(db: AsyncSession) -> Dict[str, Any]:
    """Ce que l'extension Chrome doit convertir, avec la compagnie."""
    projets = list(
        (
            await db.execute(
                select(Project)
                .where(Project.qbo_conversion_etat == A_CONVERTIR)
                .order_by(Project.created_at.asc(), Project.id.asc())
            )
        ).scalars().all()
    )
    noms = await _noms_clients(db, projets)
    qb = await etat_quickbooks(db)
    return {
        "ok": True,
        "company_name": qb["company_name"],
        "realm_id": qb["realm_id"],
        "environment": qb["environment"],
        "lien_projets": qb["lien_projets"],
        "items": [
            {
                "project_id": p.id,
                "nom": _nom_qb(p),
                "client": noms.get(p.client_id or 0) or None,
                "projet": p.name,
            }
            for p in projets
        ],
    }


async def resultat_extension(
    db: AsyncSession, resultats: List[Tuple[int, bool, Optional[str]]]
) -> Dict[str, Any]:
    """Compte rendu de l'extension (par projet : réussi ?, détail), puis
    constat par l'API : seul QuickBooks dit si c'est converti."""
    ids = [pid for pid, _, _ in resultats]
    projets = (
        list((await db.execute(select(Project).where(Project.id.in_(ids)))).scalars().all())
        if ids
        else []
    )
    par_id = {p.id: p for p in projets}
    quand = _maintenant().strftime("%Y-%m-%d %H:%M UTC")
    for pid, ok, detail in resultats:
        p = par_id.get(pid)
        if p is None:
            continue
        texte = (detail or "").strip()[:500]
        p.qbo_conversion_detail = f"{quand} · extension : " + (
            texte or ("conversion faite" if ok else "échec")
        )
    try:
        bilan = await verifier(db, projets=projets)
    except ConversionErreur as exc:
        bilan = {"erreur": exc.message, "converties": [], "restantes": [p.id for p in projets]}
    await db.flush()
    return {
        "ok": True,
        "items": [
            {"project_id": p.id, "etat": p.qbo_conversion_etat, "detail": p.qbo_conversion_detail}
            for p in projets
        ],
        "converties": bilan.get("converties", []),
        "erreur": bilan.get("erreur"),
    }
