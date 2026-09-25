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
entre deux ; trois domaines en parallèle. Un magasin qui échoue n'arrête
pas les autres. Tourne chaque jour (mega-cron ``all-daily``) et à la
demande depuis le catalogue.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select
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

    html = await fetch_rendered_html(url)
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
    price = float(releve.price)
    regular = releve.regular_price
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
) -> dict:
    """Relève toutes les offres avec lien (filtres optionnels). Avec
    ``max_age_hours``, saute celles vérifiées récemment. Un domaine à la
    fois, trois domaines en parallèle. Flush à mesure ; l'appelant
    committe."""
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
    stats = {
        "offres": len(offres), "ok": 0, "echecs": 0, "changes": 0,
        "rabais": 0, "par_domaine": {}, "erreurs": [],
    }
    if not offres:
        return stats

    # Regroupe par domaine : chaque groupe est séquentiel (politesse),
    # les groupes tournent en parallèle (borné).
    groupes: dict[str, list[MateriauOffre]] = {}
    for o in offres:
        groupes.setdefault(pm.domain_of(o.url or ""), []).append(o)
    sem = asyncio.Semaphore(PARALLELISME)
    results: list[ReleveResultat] = []

    async def _run_group(domain: str, group: list[MateriauOffre]) -> None:
        async with sem:
            d = stats["par_domaine"].setdefault(domain, {"ok": 0, "echecs": 0})
            for o in group:
                r = await relever_offre(db, o)
                results.append(r)
                d["ok" if r.ok else "echecs"] += 1
                # Site qui bloque : inutile d'insister sur les autres
                # offres du même domaine aujourd'hui.
                if not r.ok and r.method == "blocked":
                    for rest in group[group.index(o) + 1:]:
                        rest.fetch_checked_at = datetime.now(timezone.utc)
                        rest.fetch_error = r.error
                        results.append(ReleveResultat(
                            offre_id=rest.id, materiau_id=rest.materiau_id,
                            magasin_id=rest.magasin_id, ok=False, error=r.error,
                            method="blocked",
                        ))
                        d["echecs"] += 1
                    await db.flush()
                    break

    await asyncio.gather(*(_run_group(dom, grp) for dom, grp in groupes.items()))
    for r in results:
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
    log.info("Relevé prix matériaux : %s", {k: v for k, v in stats.items() if k != "erreurs"})
    return stats


async def alerter_rabais_sans_casser(db) -> int:
    """Alertes de rabais (étape 3) après un relevé : jamais bloquant."""
    try:
        from app.services.materiaux_alertes import alerter_rabais

        return await alerter_rabais(db)
    except Exception:  # noqa: BLE001
        log.exception("Alertes rabais matériaux échouées")
        return 0


#: Dernier relevé global (en mémoire, pour l'écran) : lancé/terminé/stats.
DERNIER_RELEVE: dict = {"en_cours": False, "lance_a": None, "termine_a": None, "stats": None}


async def relever_tout_en_arriere_plan(**kwargs) -> None:
    """Session fraîche + commit ; état exposé via ``DERNIER_RELEVE``."""
    from app.db.session import AsyncSessionLocal

    if DERNIER_RELEVE.get("en_cours"):
        return
    DERNIER_RELEVE.update(en_cours=True, lance_a=datetime.now(timezone.utc).isoformat(), termine_a=None)
    try:
        async with AsyncSessionLocal() as db:
            stats = await relever_tout(db, **kwargs)
            await db.commit()
            stats["alertes"] = await alerter_rabais_sans_casser(db)
            await db.commit()
        DERNIER_RELEVE["stats"] = stats
    except Exception as exc:  # noqa: BLE001
        log.exception("Relevé prix matériaux en arrière-plan échoué")
        DERNIER_RELEVE["stats"] = {"error": str(exc)[:300]}
    finally:
        DERNIER_RELEVE.update(en_cours=False, termine_a=datetime.now(timezone.utc).isoformat())
