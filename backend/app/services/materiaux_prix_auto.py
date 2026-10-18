"""Relevé automatique des prix du catalogue de matériaux (étape 2,
2026-09-25).

Pour chaque offre (matériau × magasin) qui a un LIEN PRODUIT :

1. on récupère la page — par l'API du magasin si son parseur en expose
   une (``fetch``), sinon en HTTP direct avec des en-têtes navigateur,
   et, si le site bloque notre serveur ou exige un navigateur
   (``NEEDS_BROWSER``), par le VPS de scraping (Playwright) ;
2. le parseur du magasin lit prix, prix régulier, rabais, fin de rabais,
   titre ; repli sur les données structurées standard ;
3. succès → l'offre est mise à jour (source ``auto``, ``observed_at``
   maintenant) et un point d'historique est ajouté si le prix ou le
   rabais a changé ; échec → seul ``fetch_error`` / ``fetch_checked_at``
   bougent, le prix précédent reste.

Politesse : au plus une requête à la fois par domaine, avec une pause
entre deux ; trois domaines en parallèle, chacun dans SA session (commit
par offre). Un magasin qui échoue n'arrête pas les autres. Tourne chaque
jour (mega-cron ``all-daily``) et à la demande depuis le catalogue.

Course de fond (2026-10-18, « extraction bloque ») : un seul relevé à la
fois par processus, référence de tâche gardée, durée maximale
(``DUREE_MAX_RELEVE_S``) après laquelle l'état est libéré, arrêt à la
demande (``annuler_releve``) — le travail déjà committé reste. Avant, les
trois domaines partageaient une seule AsyncSession (« another operation
is in progress » tuait la course au hasard et perdait tout), un VPS
injoignable faisait attendre chaque offre Rona/BMR jusqu'au délai réseau,
et un relevé lancé par le cron restait invisible et inarrêtable : le
bouton « Actualiser les prix » répondait « déjà en cours » des heures
durant.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.models.materiau import (
    Magasin,
    Materiau,
    MateriauOffre,
    MateriauPrixHistorique,
)
from app.services import prix_magasins as pm

log = logging.getLogger(__name__)

#: Pause entre deux requêtes vers le même domaine (secondes).
PAUSE_PAR_DOMAINE = 1.5
#: Domaines interrogés en parallèle.
PARALLELISME = 3
#: Délai réseau par page.
TIMEOUT = httpx.Timeout(25.0, connect=10.0)

_domain_locks: dict[str, asyncio.Lock] = {}
_last_hit: dict[str, float] = {}


@dataclass
class ReleveResultat:
    offre_id: int
    materiau_id: int
    magasin_id: int
    ok: bool
    price: Optional[float] = None
    regular_price: Optional[float] = None
    on_sale: bool = False
    sale_end: Optional[str] = None
    changed: bool = False
    method: str = ""
    error: Optional[str] = None


async def fetch_page(url: str) -> tuple[str, str]:
    """Retourne (contenu, méthode) : ``api`` via le parseur, ``http`` en
    direct, ``browser`` via le VPS. Lève ``pm.FetchBlocked`` si le site
    refuse et qu'aucun navigateur n'est disponible."""
    mod = pm.parser_for(url)
    if mod is not None and hasattr(mod, "fetch"):
        try:
            return await mod.fetch(url), "api"
        except pm.FetchBlocked:
            pass  # → on tente le navigateur ci-dessous
        except Exception as exc:  # noqa: BLE001
            log.info("fetch() du parseur %s a échoué (%s) → HTTP direct", mod.__name__, exc)
    needs_browser = bool(getattr(mod, "NEEDS_BROWSER", False))
    if not needs_browser:
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT, headers=pm.BROWSER_HEADERS, follow_redirects=True
            ) as client:
                r = await client.get(url)
            if r.status_code == 200 and r.text:
                return r.text, "http"
            if r.status_code in (401, 403, 429, 503):
                needs_browser = True
            else:
                raise RuntimeError(f"HTTP {r.status_code}")
        except httpx.HTTPError as exc:
            raise RuntimeError(f"réseau : {exc}") from exc
    # Navigateur (VPS Playwright).
    from app.integrations.scraping_proxy import fetch_rendered_html

    try:
        html = await fetch_rendered_html(url)
    except httpx.HTTPError as exc:
        # VPS injoignable (DNS, connexion refusée, délai) : inutile
        # d'attendre le délai réseau pour CHAQUE offre du même site —
        # même traitement qu'un site qui bloque, le relevé passe au
        # domaine suivant et réessaiera au prochain passage.
        raise pm.FetchBlocked(
            "VPS de scraping injoignable "
            f"({str(exc).strip() or exc.__class__.__name__}) : ce site exige "
            "un navigateur, le relevé reprendra quand le VPS répondra."
        ) from exc
    if html is None:
        raise pm.FetchBlocked(
            "Ce site refuse notre serveur ; le relevé exige le VPS de "
            "scraping (SCRAPING_VPS_URL / SCRAPING_VPS_KEY non configurés)."
        )
    if not html:
        raise RuntimeError("le navigateur n'a rien renvoyé")
    return html, "browser"


async def _polite(domain: str) -> None:
    lock = _domain_locks.setdefault(domain, asyncio.Lock())
    async with lock:
        loop = asyncio.get_running_loop()
        last = _last_hit.get(domain)
        if last is not None:
            wait = PAUSE_PAR_DOMAINE - (loop.time() - last)
            if wait > 0:
                await asyncio.sleep(wait)
        _last_hit[domain] = loop.time()


async def relever_offre(db, offre: MateriauOffre) -> ReleveResultat:
    """Relève UNE offre et l'enregistre (flush, pas de commit)."""
    now = datetime.now(timezone.utc)
    res = ReleveResultat(
        offre_id=offre.id, materiau_id=offre.materiau_id, magasin_id=offre.magasin_id, ok=False
    )
    url = (offre.url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        res.error = "Aucun lien produit valide sur cette offre."
        offre.fetch_error = res.error
        offre.fetch_checked_at = now
        return res
    domain = pm.domain_of(url)
    try:
        await _polite(domain)
        content, method = await fetch_page(url)
        releve = pm.parse(content, url)
    except pm.FetchBlocked as exc:
        releve, method = pm.PrixReleve(error=str(exc)), "blocked"
    except Exception as exc:  # noqa: BLE001
        releve, method = pm.PrixReleve(error=f"Page inaccessible : {exc}"), "error"

    offre.fetch_checked_at = now
    if not releve.ok:
        offre.fetch_error = (releve.error or "Prix introuvable sur la page.")[:500]
        res.error = offre.fetch_error
        res.method = method
        return res

    old_price = float(offre.unit_price) if offre.unit_price is not None else None
    old_sale = bool(offre.on_sale)
    old_end = offre.sale_end
    # Arrondi à la cent dès ici : la colonne est Numeric(12,2) et la clé
    # d'idempotence des alertes de rabais doit être la même en session et
    # relue de la base.
    price = round(float(releve.price), 2)
    regular = round(float(releve.regular_price), 2) if releve.regular_price is not None else None
    on_sale = bool(releve.on_sale or (regular is not None and regular > price + 0.005))
    sale_end = releve.sale_end if on_sale else None
    if on_sale and sale_end is None and old_sale and old_end and old_end >= now.date():
        sale_end = old_end  # la page ne répète pas la date, on garde celle connue

    changed = (
        old_price is None
        or abs(old_price - price) >= 0.005
        or old_sale != on_sale
        or old_end != sale_end
        or offre.source != "auto"
    )
    offre.unit_price = price
    offre.regular_price = regular if on_sale else None
    offre.on_sale = on_sale
    offre.sale_end = sale_end
    offre.source = "auto"
    offre.observed_at = now
    offre.fetch_error = None
    if releve.title:
        offre.page_title = releve.title[:255]
    if releve.sku and not offre.sku:
        offre.sku = releve.sku[:64]
    if changed:
        db.add(MateriauPrixHistorique(
            materiau_id=offre.materiau_id, magasin_id=offre.magasin_id,
            unit_price=price, regular_price=(regular if on_sale else None),
            on_sale=on_sale, sale_end=sale_end, source="auto", observed_at=now,
            note=f"Relevé automatique ({releve.method or method})"[:255],
        ))
    await db.flush()
    res.ok = True
    res.price, res.regular_price, res.on_sale = price, (regular if on_sale else None), on_sale
    res.sale_end = sale_end.isoformat() if sale_end else None
    res.changed, res.method = changed, (releve.method or method)
    return res


async def relever_tout(
    db,
    *,
    materiau_id: Optional[int] = None,
    magasin_id: Optional[int] = None,
    max_age_hours: Optional[float] = None,
    limit: int = 2000,
    session_factory=None,
    stats_live: Optional[dict] = None,
) -> dict:
    """Relève toutes les offres avec lien (filtres optionnels). Avec
    ``max_age_hours``, saute celles vérifiées récemment. Un domaine à la
    fois (politesse), trois domaines en parallèle.

    - ``session_factory`` (prod : ``AsyncSessionLocal``) : chaque domaine
      tourne dans SA session avec un commit par offre — une AsyncSession
      ne supporte pas plusieurs tâches en parallèle, et un commit par
      offre garde ce qui a été lu si la course s'arrête (erreur, durée
      maximale, bouton « Arrêter »). ``db`` ne sert qu'à lister les
      offres.
    - sans fabrique (tests) : séquentiel sur ``db``, flush à mesure,
      l'appelant committe.
    - ``stats_live`` : dict mis à jour EN DIRECT à chaque offre
      (examinées, lus, échecs, dernier résultat) — c'est ce que lit
      ``GET /materiaux/prix/etat`` pendant la course.
    """
    stmt = (
        select(MateriauOffre)
        .join(Materiau, Materiau.id == MateriauOffre.materiau_id)
        .join(Magasin, Magasin.id == MateriauOffre.magasin_id)
        .where(
            MateriauOffre.url.is_not(None),
            Materiau.is_active.is_(True),
            Magasin.is_active.is_(True),
        )
        .options(selectinload(MateriauOffre.magasin))
        .order_by(MateriauOffre.fetch_checked_at.asc().nulls_first(), MateriauOffre.id.asc())
        .limit(limit)
    )
    if materiau_id is not None:
        stmt = stmt.where(MateriauOffre.materiau_id == materiau_id)
    if magasin_id is not None:
        stmt = stmt.where(MateriauOffre.magasin_id == magasin_id)
    offres = list((await db.execute(stmt)).scalars().all())
    if max_age_hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        offres = [
            o for o in offres
            if o.fetch_checked_at is None or o.fetch_checked_at < cutoff
        ]
    stats = stats_live if stats_live is not None else {}
    stats.update({
        "offres": len(offres), "examinees": 0, "ok": 0, "echecs": 0, "changes": 0,
        "rabais": 0, "par_domaine": {}, "erreurs": [], "dernier": None,
    })
    if not offres:
        return stats

    # Regroupe par domaine : chaque groupe est séquentiel (politesse),
    # les groupes tournent en parallèle (borné). On ne garde que des ids :
    # chaque groupe recharge ses offres dans sa propre session.
    groupes: dict[str, list[int]] = {}
    cles: dict[int, tuple[int, int]] = {}
    for o in offres:
        groupes.setdefault(pm.domain_of(o.url or ""), []).append(o.id)
        cles[o.id] = (o.materiau_id, o.magasin_id)
    sem = asyncio.Semaphore(PARALLELISME)

    def _compter(domain: str, r: ReleveResultat) -> None:
        d = stats["par_domaine"].setdefault(domain, {"ok": 0, "echecs": 0})
        d["ok" if r.ok else "echecs"] += 1
        stats["examinees"] += 1
        if r.ok:
            stats["ok"] += 1
            stats["changes"] += int(r.changed)
            stats["rabais"] += int(r.on_sale)
        else:
            stats["echecs"] += 1
            if len(stats["erreurs"]) < 25:
                stats["erreurs"].append(
                    {"offre_id": r.offre_id, "materiau_id": r.materiau_id,
                     "magasin_id": r.magasin_id, "error": r.error}
                )
        stats["dernier"] = {
            "domaine": domain, "materiau_id": r.materiau_id, "magasin_id": r.magasin_id,
            "ok": r.ok, "price": r.price, "error": (r.error or "")[:160] or None,
            "a": datetime.now(timezone.utc).isoformat(),
        }

    async def _relever_ids(s, domain: str, ids: list[int], *, commit: bool) -> None:
        for i, oid in enumerate(ids):
            off = await s.get(MateriauOffre, oid)
            if off is None:
                continue
            r = await relever_offre(s, off)
            _compter(domain, r)
            if commit:
                await s.commit()
            # Site qui bloque (ou VPS injoignable) : inutile d'insister sur
            # les autres offres du même domaine aujourd'hui.
            if not r.ok and r.method == "blocked":
                reste = ids[i + 1:]
                if reste:
                    now = datetime.now(timezone.utc)
                    await s.execute(
                        update(MateriauOffre)
                        .where(MateriauOffre.id.in_(reste))
                        .values(fetch_checked_at=now, fetch_error=(r.error or "")[:500])
                    )
                    if commit:
                        await s.commit()
                    else:
                        await s.flush()
                    for rid in reste:
                        mid, gid = cles.get(rid, (0, 0))
                        _compter(domain, ReleveResultat(
                            offre_id=rid, materiau_id=mid, magasin_id=gid,
                            ok=False, error=r.error, method="blocked",
                        ))
                break

    async def _run_group(domain: str, ids: list[int]) -> None:
        async with sem:
            try:
                if session_factory is not None:
                    async with session_factory() as s:
                        await _relever_ids(s, domain, ids, commit=True)
                else:
                    await _relever_ids(db, domain, ids, commit=False)
            except Exception as exc:  # noqa: BLE001 — un domaine KO n'arrête pas les autres
                log.exception("Relevé prix matériaux : domaine %s en erreur", domain)
                d = stats["par_domaine"].setdefault(domain, {"ok": 0, "echecs": 0})
                d["erreur"] = (str(exc).strip() or exc.__class__.__name__)[:200]

    if session_factory is not None:
        await asyncio.gather(*(_run_group(dom, ids) for dom, ids in groupes.items()))
    else:
        # Une seule session : jamais deux domaines en même temps dessus.
        for dom, ids in groupes.items():
            await _run_group(dom, ids)
    log.info("Relevé prix matériaux : %s", {k: v for k, v in stats.items() if k not in ("erreurs", "dernier")})
    return stats


async def alerter_rabais_sans_casser(db) -> int:
    """Alertes de rabais (étape 3) après un relevé : jamais bloquant."""
    try:
        from app.services.materiaux_alertes import alerter_rabais

        return await alerter_rabais(db)
    except Exception:  # noqa: BLE001
        log.exception("Alertes rabais matériaux échouées")
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return 0


#: Dernier relevé global (en mémoire, pour l'écran) : lancé/terminé/stats.
DERNIER_RELEVE: dict = {"en_cours": False, "lance_a": None, "termine_a": None, "stats": None}
#: Durée maximale d'une course : au-delà, elle s'arrête d'elle-même et
#: l'état est libéré (un relevé « en cours » depuis des heures bloquait le
#: bouton « Actualiser les prix » et le passage du cron).
DUREE_MAX_RELEVE_S = 2 * 3600
#: Références des tâches de fond (jamais ramassées par le GC en vol) et
#: tâche qui porte la course en cours (cible du bouton « Arrêter »).
_TACHES: set = set()
_TACHE_EN_COURS: Optional[asyncio.Task] = None


def duree_lisible(secondes: float) -> str:
    """7 320 → « 2 h 02 min » ; 540 → « 9 min » ; 42 → « 42 s »."""
    s = max(0, int(secondes))
    h, m = divmod(s // 60, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min"
    return f"{s} s"


def avec_duree(etat: dict) -> dict:
    """Copie de l'état d'une course pour l'écran : ``duree_s`` depuis le
    lancement (course en cours) ou jusqu'à la fin (course terminée)."""
    import copy

    out = copy.deepcopy(etat)
    lance = out.get("lance_a")
    fin = out.get("termine_a")
    if lance:
        try:
            debut = datetime.fromisoformat(lance)
            borne = datetime.fromisoformat(fin) if (fin and not out.get("en_cours")) else datetime.now(timezone.utc)
            out["duree_s"] = max(0, int((borne - debut).total_seconds()))
        except ValueError:
            out["duree_s"] = None
    else:
        out["duree_s"] = None
    return out


async def relever_tout_en_arriere_plan(**kwargs) -> dict:
    """Course complète : session par domaine, commit par offre, puis
    alertes de rabais ; état exposé via ``DERNIER_RELEVE``. Un seul run à
    la fois par processus, borné à ``DUREE_MAX_RELEVE_S``, arrêtable par
    ``annuler_releve`` (les prix déjà enregistrés restent). Renvoie les
    stats de la course (ou celles de la course déjà en cours)."""
    global _TACHE_EN_COURS
    from app.db.session import AsyncSessionLocal

    if DERNIER_RELEVE.get("en_cours"):
        return dict(DERNIER_RELEVE.get("stats") or {})
    live: dict = {}
    _TACHE_EN_COURS = asyncio.current_task()
    DERNIER_RELEVE.update(
        en_cours=True, lance_a=datetime.now(timezone.utc).isoformat(), termine_a=None,
        stats=live, duree_max_s=DUREE_MAX_RELEVE_S,
    )

    async def _course() -> None:
        async with AsyncSessionLocal() as db:
            await relever_tout(db, session_factory=AsyncSessionLocal, stats_live=live, **kwargs)
            live["alertes"] = await alerter_rabais_sans_casser(db)
            await db.commit()

    try:
        await asyncio.wait_for(_course(), timeout=DUREE_MAX_RELEVE_S)
    except asyncio.TimeoutError:
        log.warning("Relevé prix matériaux : arrêté après %s (durée maximale)", duree_lisible(DUREE_MAX_RELEVE_S))
        live["error"] = (
            f"Arrêté après {duree_lisible(DUREE_MAX_RELEVE_S)} (durée maximale) : "
            "les prix lus jusque-là sont enregistrés, relance « Actualiser les prix » pour continuer."
        )
    except asyncio.CancelledError:
        # Bouton « Arrêter » (ou arrêt du serveur) : on libère l'état et on
        # garde ce qui a été committé. Pas de relance de l'annulation :
        # personne n'attend cette tâche autrement que pour ses stats.
        log.info("Relevé prix matériaux : arrêté à la demande")
        live["annule"] = True
        live["error"] = "Arrêté à la demande : les prix lus jusque-là sont enregistrés."
    except Exception as exc:  # noqa: BLE001
        log.exception("Relevé prix matériaux en arrière-plan échoué")
        live["error"] = str(exc)[:300]
    finally:
        _TACHE_EN_COURS = None
        DERNIER_RELEVE.update(en_cours=False, termine_a=datetime.now(timezone.utc).isoformat())
    return dict(live)


def lancer_releve_en_fond(**kwargs) -> Optional[asyncio.Task]:
    """Démarre le relevé en tâche de fond (le bouton et le cron répondent
    tout de suite ; ``await`` sur la tâche renvoie les stats). ``None`` si
    un relevé est déjà en cours."""
    if DERNIER_RELEVE.get("en_cours"):
        return None
    task = asyncio.create_task(relever_tout_en_arriere_plan(**kwargs))
    _TACHES.add(task)
    task.add_done_callback(_TACHES.discard)
    return task


def annuler_releve() -> bool:
    """Arrête le relevé en cours (bouton « Arrêter ») : la tâche est
    annulée et l'état libéré ; les prix déjà enregistrés restent. True si
    un relevé tournait (ou si un état orphelin a été libéré)."""
    t = _TACHE_EN_COURS
    if t is not None and not t.done():
        t.cancel()
        return True
    if DERNIER_RELEVE.get("en_cours"):
        # Drapeau sans tâche vivante (ne devrait pas arriver) : on le
        # libère plutôt que de laisser le bouton bloqué.
        stats = DERNIER_RELEVE.get("stats")
        if isinstance(stats, dict):
            stats.setdefault("error", "État réinitialisé : la tâche du relevé avait disparu.")
        DERNIER_RELEVE.update(en_cours=False, termine_a=datetime.now(timezone.utc).isoformat())
        return True
    return False
