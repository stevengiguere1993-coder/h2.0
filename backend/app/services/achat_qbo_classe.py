"""Classe « Construction » sur les reçus du volet construction DÉJÀ dans
QuickBooks (Steven 2026-11-03).

Depuis le 2026-10-17, chaque reçu poussé de Kratos vers QB porte
Client : Projet + la classe « Construction » (achat_qbo). Mais un reçu
saisi directement dans QuickBooks (puis importé dans Kratos par le pull
QB → Kratos) garde la classe que la personne y a mise — souvent l'adresse
du chantier, l'ancienne convention (reçu 8077 de Planchers Économiques,
projet 1616 Saint-Alexandre : classe « 1616 Saint-Alexandre, Longueuil »
au lieu de « Construction »). Steven : « on a le client et le projet, et
la classe doit être Construction sur tous les reçus entrés par le volet
construction de Kratos ».

Ici : relecture de la transaction QB liée à un achat (Purchase ou Bill)
et correction CIBLÉE de ses lignes — même mécanique que le flip du
BillableStatus (achat_qbo.set_qbo_billable_status), jamais un re-push
complet qui écraserait la catégorie, la description ou les taxes posées
par la comptabilité :

- une ligne qui appartient à un projet Kratos (son CustomerRef est le
  sous-client QB d'un projet, ou sa classe est l'adresse d'un chantier)
  reçoit la classe « Construction » ; si elle n'avait pas de client, le
  sous-client du projet est posé (on garde « le client et le projet ») ;
- une ligne d'un autre client / d'un autre volet n'est pas touchée ;
- une transaction à une seule ligne prend le projet de l'achat Kratos
  qui la porte, même si QB ne l'identifie pas.

Rattrapage : une fois pour tous les achats liés à QB (one-shot
`achats_classe_construction_v1`, filet horaire), puis chaque heure pour
les achats créés récemment (les imports QB → Kratos).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.quickbooks import QuickBooksError, get_qbo
from app.models.achat import Achat
from app.models.project import Project

log = logging.getLogger(__name__)

CLE_RATTRAPAGE = "achats_classe_construction_v1"
#: Achats relus à chaque passage horaire après le rattrapage : ceux créés
#: depuis peu (un import QB → Kratos crée l'achat à l'heure du pull).
FENETRE_RECENTS = timedelta(hours=3)
MAX_RATTRAPAGE = 1500

_DETAILS = ("AccountBasedExpenseLineDetail", "ItemBasedExpenseLineDetail")


def _lignes_detail(txn: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Les détails (compte / article) des lignes de dépense de la
    transaction, dans l'ordre."""
    out: List[Dict[str, Any]] = []
    for line in txn.get("Line") or []:
        for key in _DETAILS:
            d = line.get(key)
            if isinstance(d, dict):
                out.append(d)
    return out


async def projets_par_sous_client(db: AsyncSession) -> Dict[str, Project]:
    """Projets Kratos indexés par leur sous-client QB (qbo_job_id)."""
    rows = (
        await db.execute(select(Project).where(Project.qbo_job_id.is_not(None)))
    ).scalars().all()
    return {str(p.qbo_job_id): p for p in rows if p.qbo_job_id}


async def _projet_de_la_ligne(
    db: AsyncSession,
    detail: Dict[str, Any],
    par_sous_client: Dict[str, Project],
    cache_classes: Dict[str, Optional[Project]],
) -> Optional[Project]:
    cref = str((detail.get("CustomerRef") or {}).get("value") or "")
    if cref and cref in par_sous_client:
        return par_sous_client[cref]
    cname = ((detail.get("ClassRef") or {}).get("name") or "").strip()
    if not cname:
        return None
    if cname not in cache_classes:
        from app.services.achat_qbo_pull import _find_project_by_class

        cache_classes[cname] = await _find_project_by_class(db, cname)
    return cache_classes[cname]


async def reclasser_lignes(
    db: AsyncSession,
    txn: Dict[str, Any],
    *,
    class_id: str,
    class_name: str,
    projet_par_defaut: Optional[Project] = None,
    par_sous_client: Optional[Dict[str, Project]] = None,
) -> int:
    """Pose la classe « Construction » (``class_id``) sur les lignes des
    projets Kratos de la transaction, en place. Renvoie le nombre de
    lignes modifiées (0 = rien à envoyer à QB)."""
    if par_sous_client is None:
        par_sous_client = await projets_par_sous_client(db)
    cache: Dict[str, Optional[Project]] = {}
    lignes = _lignes_detail(txn)
    modifiees = 0
    for d in lignes:
        projet = await _projet_de_la_ligne(db, d, par_sous_client, cache)
        if projet is None and projet_par_defaut is not None and len(lignes) == 1:
            projet = projet_par_defaut
        if projet is None:
            continue
        if str((d.get("ClassRef") or {}).get("value") or "") == str(class_id):
            continue
        d["ClassRef"] = {"value": str(class_id), "name": class_name}
        if not (d.get("CustomerRef") or {}).get("value") and projet.qbo_job_id:
            d["CustomerRef"] = {"value": str(projet.qbo_job_id)}
            d.setdefault("BillableStatus", "NotBillable")
        modifiees += 1
    return modifiees


async def _lire_transaction(
    qbo: Any, qbo_id: str
) -> Tuple[str, Dict[str, Any]]:
    """(« purchase » | « bill », objet QB) — l'id d'un achat lié peut
    désigner l'un ou l'autre (qbo_bill_id porte les deux)."""
    try:
        obj = await qbo.get_purchase(qbo_id)
        return "purchase", (obj.get("Purchase") or obj)
    except QuickBooksError:
        obj = await qbo.get_bill(qbo_id)
        return "bill", (obj.get("Bill") or obj)


async def reclasser_transaction(
    db: AsyncSession,
    qbo: Any,
    *,
    qbo_id: str,
    class_id: str,
    projet_par_defaut: Optional[Project] = None,
    par_sous_client: Optional[Dict[str, Project]] = None,
) -> Dict[str, Any]:
    """Relit la transaction QB, corrige la classe de ses lignes de projet
    et la renvoie telle quelle autrement (mise à jour de l'objet relu,
    comme le flip du BillableStatus). Lève QuickBooksError."""
    kind, obj = await _lire_transaction(qbo, qbo_id)
    n = await reclasser_lignes(
        db,
        obj,
        class_id=class_id,
        class_name=(settings.qbo_achat_class_name or "").strip(),
        projet_par_defaut=projet_par_defaut,
        par_sous_client=par_sous_client,
    )
    if n == 0:
        return {"ok": True, "unchanged": True, "kind": kind, "qbo_id": qbo_id}
    obj.pop("sparse", None)
    if kind == "purchase":
        await qbo.update_purchase(obj)
    else:
        await qbo.update_bill(obj)
    log.info(
        "Classe « %s » posée sur %s ligne(s) de la %s QB %s",
        settings.qbo_achat_class_name, n, kind, qbo_id,
    )
    return {"ok": True, "kind": kind, "qbo_id": qbo_id, "lignes": n}


async def reclasser_classe_qb_achat(
    db: AsyncSession, achat_id: int
) -> Dict[str, Any]:
    """Classe « Construction » sur la transaction QB liée à cet achat de
    chantier. Best-effort : ne lève pas, renvoie le détail."""
    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        return {"skipped": "qbo_not_configured"}
    from app.services.achat_qbo import _classe_achats_id, _load_achat

    achat = await _load_achat(db, achat_id)
    if achat is None:
        return {"skipped": "achat_introuvable"}
    qbo_id = str(achat.qbo_purchase_id or achat.qbo_bill_id or "")
    if not qbo_id:
        return {"skipped": "aucun_lien_qb"}
    if not achat.project_id:
        return {"skipped": "sans_projet"}
    projet = await db.get(Project, achat.project_id)
    class_id = await _classe_achats_id(qbo, int(achat.id))
    if not class_id:
        return {"skipped": "classe_indisponible"}
    try:
        return await reclasser_transaction(
            db, qbo, qbo_id=qbo_id, class_id=class_id, projet_par_defaut=projet
        )
    except QuickBooksError as exc:
        # Lien périmé (610 Object Not Found) ou refus QB : on note, on
        # n'insiste pas — le reçu reste tel quel dans QuickBooks.
        log.warning(
            "Achat %s : classe Construction sur QB %s refusée : %s",
            achat_id, qbo_id, exc,
        )
        return {"error": str(exc)[:200]}


async def _rattrapage_fait(db: AsyncSession) -> bool:
    return (
        await db.execute(
            text("SELECT 1 FROM applied_backfills WHERE key = :k"),
            {"k": CLE_RATTRAPAGE},
        )
    ).first() is not None


async def _marquer_rattrapage(db: AsyncSession) -> None:
    await db.execute(
        text(
            "INSERT INTO applied_backfills (key) VALUES (:k) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"k": CLE_RATTRAPAGE},
    )


async def candidats(db: AsyncSession, *, tous: bool) -> List[Tuple[int, str]]:
    """(achat_id, id QB) des achats de chantier liés à QB — tous (rattrapage)
    ou créés récemment (imports). Une seule entrée par transaction QB (un
    reçu fractionné ou divisé a plusieurs achats sur la même)."""
    stmt = (
        select(Achat.id, Achat.qbo_purchase_id, Achat.qbo_bill_id)
        .where(
            Achat.project_id.is_not(None),
            Achat.qbo_purchase_id.is_not(None) | Achat.qbo_bill_id.is_not(None),
        )
        .order_by(Achat.id)
    )
    if not tous:
        # created_at est TIMESTAMPTZ : borne en UTC avec fuseau.
        depuis = datetime.now(timezone.utc) - FENETRE_RECENTS
        stmt = stmt.where(Achat.created_at >= depuis)
    stmt = stmt.limit(MAX_RATTRAPAGE)
    vus: set[str] = set()
    out: List[Tuple[int, str]] = []
    for aid, pid, bid in (await db.execute(stmt)).all():
        qbo_id = str(pid or bid or "")
        if not qbo_id or qbo_id in vus:
            continue
        vus.add(qbo_id)
        out.append((int(aid), qbo_id))
    return out


async def reclasser_achats_lies() -> Dict[str, Any]:
    """Filet horaire : une fois tous les achats liés à QB (rattrapage,
    marqueur posé seulement si QB a répondu), puis les achats récents.
    Chaque transaction dans sa propre session ; les erreurs sont comptées,
    jamais fatales."""
    from app.db.session import AsyncSessionLocal

    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        return {"skipped": "qbo_not_configured"}
    async with AsyncSessionLocal() as db:
        tous = not await _rattrapage_fait(db)
        liste = await candidats(db, tous=tous)
    res: Dict[str, Any] = {
        "rattrapage": tous, "candidats": len(liste),
        "modifies": 0, "inchanges": 0, "erreurs": 0, "sautes": 0,
    }
    for aid, _qbo_id in liste:
        try:
            async with AsyncSessionLocal() as db:
                r = await reclasser_classe_qb_achat(db, aid)
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            res["erreurs"] += 1
            log.error("Classe Construction : achat %s en erreur : %s", aid, exc)
            continue
        if r.get("error"):
            res["erreurs"] += 1
        elif r.get("skipped"):
            res["sautes"] += 1
        elif r.get("unchanged"):
            res["inchanges"] += 1
        else:
            res["modifies"] += 1
    if tous:
        async with AsyncSessionLocal() as db:
            await _marquer_rattrapage(db)
            await db.commit()
    if res["modifies"] or res["erreurs"]:
        log.warning("Classe Construction sur les reçus QB : %s", res)
    return res
