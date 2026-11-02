"""Filet : sous-client QB d'un projet resté sous l'ANCIEN client mère.

Steven (2026-11-02) : « le client du projet 1660 Saint-Clément a changé
dans Kratos. Il ne s'est pas changé dans QuickBooks. 1660 Saint-Clément
devrait maintenant être sous-client du client mère Groupe 1660
Saint-Clément inc. Le système devrait vérifier si Groupe 1660
Saint-Clément inc. existe dans QuickBooks et effectuer le changement. »

Le changement de client sur la fiche du projet lance déjà
``push_project_qbo_job_now`` (en fond) : le client mère est retrouvé ou
créé (``qbo_client_mere``), puis ``resolve_project_customer_id`` DÉPLACE
le sous-client sous lui. Ce filet horaire (``qbo_nets``) rattrape ce que
ce passage en fond aurait manqué (QuickBooks injoignable, projet changé
avant ce correctif) : tout projet dont le sous-client QB est sous un
autre client mère que celui de sa fiche client est repassé dans la même
mécanique.

Réparation ponctuelle (une fois, ``applied_backfills``) : avant ce
correctif, Kratos pouvait avoir CRÉÉ un second sous-client sous le
nouveau client, au nom dérivé (« adresse — nom du projet », le nom
d'affichage étant unique dans QuickBooks), en laissant l'original sous
l'ancien client. Pour les projets de Groupe 1660 Saint-Clément, on
déplace l'original sous le bon client, on y relie le projet et on rend
le doublon inactif s'il n'a pas de solde.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select, text

log = logging.getLogger(__name__)

#: Projets repassés au plus par passage (borne de sécurité).
MAX_PAR_PASSAGE = 50

#: v2 (2026-11-02, après la mise en prod) : la v1 avait gardé le lien de
#: la fiche du Groupe vers le client QB #179, qui n'est pas « Groupe 1660
#: Saint-Clément inc. » (autre compagnie au même courriel). La v2 repasse
#: avec la règle du nom (``qbo_client_mere``) : client mère retrouvé /
#: réactivé / créé au bon nom, sous-client déplacé sous lui.
CLE_REPARATION_1660 = "qbo_sous_client_1660_st_clement_v2"


def _parent_de(row: Optional[Dict[str, Any]]) -> str:
    return str(((row or {}).get("ParentRef") or {}).get("value") or "")


async def _qbo_pret() -> Any:
    from app.integrations.quickbooks import get_qbo

    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    return qbo if qbo.ready else None


async def _clients_qb(qbo: Any) -> Dict[str, Dict[str, Any]]:
    rows = await qbo.query_all("SELECT * FROM Customer")
    return {str(r.get("Id")): r for r in rows if r.get("Id")}


async def projets_sous_le_mauvais_client(
    clients_qb: Dict[str, Dict[str, Any]],
) -> List[int]:
    """Projets dont le sous-client QB lié est sous un autre client mère
    que le client QB mémorisé sur la fiche client du projet."""
    from app.db.session import AsyncSessionLocal
    from app.models.client import Client
    from app.models.project import Project

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Project.id, Project.qbo_job_id, Client.qbo_customer_id)
                .join(Client, Client.id == Project.client_id)
                .where(Project.qbo_job_id.is_not(None))
                .order_by(Project.id)
            )
        ).all()
    out: List[int] = []
    for pid, jid, lien_client in rows:
        row = clients_qb.get(str(jid or "").strip())
        parent = _parent_de(row)
        if not parent:
            continue  # sous-client disparu / converti, ou client mère lui-même
        if not lien_client or parent == str(lien_client):
            # Fiche sans client QB mémorisé : rien ne dit que le parent
            # actuel est faux (le prochain envoi le constatera).
            continue
        out.append(int(pid))
    return out


async def _repasser(project_id: int) -> Optional[Dict[str, Any]]:
    from app.db.session import AsyncSessionLocal
    from app.models.project import Project
    from app.services.bon_project import (
        ensure_project_qbo_job,
        record_project_qbo_error,
    )

    async with AsyncSessionLocal() as db:
        proj = await db.get(Project, project_id)
        if proj is None or not proj.client_id:
            return None
        try:
            res = await ensure_project_qbo_job(db, proj)
            proj.qbo_sync_error = None
            await db.commit()
            return res
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            log.warning("Projet %s : sous-client QB non replacé : %s", project_id, exc)
            await record_project_qbo_error(project_id, str(exc))
            return None


async def _reparer_doublon(project_id: int, qbo: Any) -> Optional[str]:
    """Le projet est relié à un sous-client au nom DÉRIVÉ sous le bon
    client, alors que l'original (nom = adresse exacte, relié à aucun
    projet) est resté sous un autre client : on déplace l'original, on y
    relie le projet, et le doublon devient inactif s'il n'a pas de solde.
    Retourne l'id de l'original relié, sinon None."""
    from app.db.session import AsyncSessionLocal
    from app.models.client import Client
    from app.models.project import Project
    from app.services import qbo_projets_conversion as conversion
    from app.services.qbo_project_resolve import _local_name_of, _norm

    clients_qb = await _clients_qb(qbo)
    async with AsyncSessionLocal() as db:
        proj = await db.get(Project, project_id)
        if proj is None or not proj.client_id or not proj.qbo_job_id:
            return None
        client = await db.get(Client, proj.client_id)
        parent = str((client.qbo_customer_id if client else "") or "")
        actuel = clients_qb.get(str(proj.qbo_job_id))
        voulu = _norm(proj.address) if (proj.kind or "") != "bon_travail" else _norm(proj.name)
        if not parent or actuel is None or not voulu:
            return None
        if _norm(_local_name_of(actuel)) == voulu:
            return None  # déjà relié au sous-client au nom exact
        lies = {
            str(j)
            for (j,) in (
                await db.execute(select(Project.qbo_job_id).where(Project.qbo_job_id.is_not(None)))
            ).all()
        }
        originaux = [
            r
            for cid, r in clients_qb.items()
            if _parent_de(r)
            and _parent_de(r) != parent
            and cid not in lies
            and _norm(_local_name_of(r)) == voulu
        ]
        if len(originaux) != 1:
            return None
        original = originaux[0]
        oid = str(original["Id"])
        deplace = await qbo.move_subcustomer(oid, parent)
        if not deplace or _parent_de(deplace) not in ("", parent):
            return None
        doublon = str(proj.qbo_job_id)
        proj.qbo_job_id = oid
        conversion.demander(proj, deplace if isinstance(deplace, dict) else original)
        proj.qbo_sync_error = None
        await db.commit()
        log.warning(
            "Projet %s « %s » : sous-client QB original %s déplacé sous le client "
            "%s et relié ; doublon %s à rendre inactif.",
            proj.id, proj.name, oid, parent, doublon,
        )
    try:
        solde = float((clients_qb.get(doublon) or {}).get("Balance") or 0)
        if solde == 0 and doublon != oid:
            await qbo.deactivate_customer(doublon)
    except Exception as exc:  # noqa: BLE001
        log.warning("Doublon QB %s non désactivé : %s", doublon, exc)
    return oid


async def _reparation_1660(qbo: Any) -> Optional[Dict[str, Any]]:
    """Une fois : projets de « Groupe 1660 Saint-Clément » (Steven
    2026-11-02) — client mère vérifié / créé, sous-client déplacé, doublon
    éventuel résorbé."""
    from app.db.session import AsyncSessionLocal
    from app.models.client import Client
    from app.models.project import Project
    from app.services.qbo_project_resolve import _norm

    async with AsyncSessionLocal() as db:
        deja = (
            await db.execute(
                text("SELECT 1 FROM applied_backfills WHERE key = :k"),
                {"k": CLE_REPARATION_1660},
            )
        ).first()
        if deja is not None:
            return None
        rows = (
            await db.execute(
                select(Project.id, Client.name).join(Client, Client.id == Project.client_id)
            )
        ).all()
    cibles = [int(pid) for pid, nom in rows if "1660 st clement" in _norm(nom)]
    bilan: Dict[str, Any] = {"projets": cibles, "replaces": [], "originaux": []}
    for pid in cibles:
        res = await _repasser(pid)
        if res:
            bilan["replaces"].append({"projet": pid, "action": res.get("action")})
        try:
            oid = await _reparer_doublon(pid, qbo)
            if oid:
                bilan["originaux"].append({"projet": pid, "sous_client": oid})
        except Exception as exc:  # noqa: BLE001
            log.warning("Réparation 1660 projet %s : %s", pid, exc)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO applied_backfills (key) VALUES (:k) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"k": CLE_REPARATION_1660},
        )
        await db.commit()
    log.warning("Réparation QB 1660 Saint-Clément : %s", bilan)
    return bilan


#: Fiches corrigées au plus par passage (borne de sécurité).
MAX_LIENS_PAR_PASSAGE = 30
KIND_LIEN_CORRIGE = "qbo_lien_client_corrige"


async def corriger_liens_autre_compagnie(
    qbo: Any, clients_qb: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Fiches client reliées au client QB d'une AUTRE compagnie (nom
    incompatible, ``qbo_noms.lien_acceptable``) — héritage du repli par
    courriel, les compagnies d'un même propriétaire partageant courriel et
    personne contact (Steven 2026-11-02 : « il faut éviter que cela se
    reproduise »). Une fiche dont des projets ont un sous-client QB est
    repassée par la synchro du projet (client mère au bon nom retrouvé,
    réactivé ou créé ; sous-clients déplacés dessous) ; sans projet relié,
    le lien est simplement retiré (le prochain envoi retrouvera le bon
    client par son nom). Les admins sont prévenus dans la cloche."""
    from app.db.session import AsyncSessionLocal
    from app.integrations.qbo_noms import lien_acceptable
    from app.models.client import Client
    from app.models.project import Project
    from app.services.notifications import notify_role

    async with AsyncSessionLocal() as db:
        fiches = (
            await db.execute(
                select(Client.id, Client.name, Client.qbo_customer_id).where(
                    Client.qbo_customer_id.is_not(None)
                )
            )
        ).all()
    fautives = []
    for cid, nom, lien in fiches:
        row = clients_qb.get(str(lien or "").strip())
        if row is None or _parent_de(row):
            continue  # client QB inactif / disparu, ou sous-client : autre filet
        if lien_acceptable(nom, row.get("DisplayName")):
            continue
        fautives.append((int(cid), nom, str(lien), row.get("DisplayName") or ""))
    corrigees: List[Dict[str, Any]] = []
    for cid, nom, lien, nom_qb in fautives[:MAX_LIENS_PAR_PASSAGE]:
        async with AsyncSessionLocal() as db:
            pids = [
                int(p)
                for (p,) in (
                    await db.execute(
                        select(Project.id).where(
                            Project.client_id == cid,
                            Project.qbo_job_id.is_not(None),
                        )
                    )
                ).all()
            ]
            if not pids:
                c = await db.get(Client, cid)
                if c is not None and str(c.qbo_customer_id or "") == lien:
                    c.qbo_customer_id = None
                    await db.commit()
        for pid in pids:
            await _repasser(pid)
        async with AsyncSessionLocal() as db:
            c = await db.get(Client, cid)
            apres = c.qbo_customer_id if c is not None else None
        if str(apres or "") == lien:
            # La synchro du projet a échoué (QB injoignable, refus) : on
            # réessaiera au prochain passage, sans annoncer de correction.
            log.warning(
                "Fiche client %s « %s » toujours reliée au client QB %s « %s » "
                "(autre compagnie) : correction à reprendre.",
                cid, nom, lien, nom_qb,
            )
            continue
        corrigees.append(
            {"client": cid, "nom": nom, "ancien": lien, "ancien_nom": nom_qb,
             "nouveau": apres, "projets": pids}
        )
        log.warning(
            "Fiche client %s « %s » reliée au client QB %s « %s » (autre "
            "compagnie) : lien corrigé → %s (projets repassés : %s).",
            cid, nom, lien, nom_qb, apres, pids,
        )
    if corrigees:
        try:
            lignes = "; ".join(
                f"« {c['nom']} » n'est plus reliée à « {c['ancien_nom']} »"
                for c in corrigees[:5]
            )
            plus = f" (+{len(corrigees) - 5} autres)" if len(corrigees) > 5 else ""
            async with AsyncSessionLocal() as db:
                await notify_role(
                    db,
                    min_role="admin",
                    kind=KIND_LIEN_CORRIGE,
                    title=(
                        f"QuickBooks : {len(corrigees)} fiche(s) client reliée(s) "
                        "à une autre compagnie, corrigée(s)"
                    ),
                    body=(
                        lignes + plus + ". Même courriel ou même contact ne veut "
                        "pas dire même compagnie : chaque fiche a maintenant son "
                        "propre client QuickBooks à son nom."
                    ),
                    href=(
                        f"/app/clients/{corrigees[0]['client']}"
                        if len(corrigees) == 1 else "/app/clients"
                    ),
                    push=False,
                )
                await db.commit()
        except Exception:  # noqa: BLE001
            log.warning("Notification des liens QB corrigés échouée", exc_info=True)
    return {"fautives": len(fautives), "corrigees": corrigees}


async def filet_sous_clients_client_change() -> Dict[str, Any]:
    """Passage horaire : replace sous le bon client mère les sous-clients
    des projets dont le client a changé dans Kratos."""
    qbo = await _qbo_pret()
    if qbo is None:
        return {"skipped": "quickbooks_non_connecte"}
    out: Dict[str, Any] = {}
    rep = await _reparation_1660(qbo)
    if rep is not None:
        out["reparation_1660"] = rep
    try:
        liens = await corriger_liens_autre_compagnie(qbo, await _clients_qb(qbo))
        if liens["fautives"]:
            out["liens_autre_compagnie"] = liens
    except Exception:  # noqa: BLE001
        log.warning("Correction des liens QB vers une autre compagnie échouée", exc_info=True)
    ids = await projets_sous_le_mauvais_client(await _clients_qb(qbo))
    out["candidats"] = len(ids)
    actions: Dict[str, int] = {}
    for pid in ids[:MAX_PAR_PASSAGE]:
        res = await _repasser(pid)
        cle = (res or {}).get("action") or "echec"
        actions[cle] = actions.get(cle, 0) + 1
    if actions:
        out["actions"] = actions
        log.warning("Sous-clients QB replacés sous le client du projet : %s", actions)
    return out
