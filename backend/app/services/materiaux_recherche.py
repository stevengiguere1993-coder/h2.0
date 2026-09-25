"""Prix de BASE automatiques du catalogue de matériaux (2026-09-26) :
pour chaque matériau sans offre (ou sans lien produit) chez une
quincaillerie principale, on cherche le produit sur le site du magasin,
on retient le candidat qui correspond (``prix_magasins.recherche``), on
crée l'offre avec son lien et son prix, puis on relève la page produit
comme au quotidien.

- ``chercher_pour_materiau(db, materiau, magasins)`` : un matériau, tous
  les magasins demandés — renvoie le détail par magasin (trouvé /
  candidats écartés / erreur).
- ``chercher_tout(db, limit=…)`` : tous les manques, borné, un domaine à
  la fois (politesse) ; appelé par le cron après le relevé quotidien et
  par le bouton « Trouver les prix ».

Une offre trouvée par recherche porte ``source="auto"`` et une ``note``
« Trouvé automatiquement… » : l'utilisateur voit le titre lu sur le site
(``page_title``) pour contrôler que c'est bien le bon article, et peut
corriger le lien à la main. Sans correspondance suffisante on ne pose
RIEN (pas de prix plutôt qu'un mauvais prix).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.materiau import Magasin, Materiau, MateriauOffre, MateriauPrixHistorique
from app.services import prix_magasins as pm
from app.services.materiaux_prix_auto import PARALLELISME, _polite, relever_offre
from app.services.prix_magasins.recherche import Candidat, choisir, variantes

log = logging.getLogger(__name__)

NOTE_AUTO = "Trouvé automatiquement par recherche sur le site — vérifier que c'est le bon article."


@dataclass
class ResultatRecherche:
    magasin_id: int
    magasin_name: str
    ok: bool = False
    #: trouve | deja | aucun | erreur | non_supporte
    statut: str = "aucun"
    url: Optional[str] = None
    title: Optional[str] = None
    score: Optional[float] = None
    price: Optional[float] = None
    regular_price: Optional[float] = None
    on_sale: bool = False
    #: Comment le prix a été obtenu : releve (page produit) | recherche.
    method: str = ""
    error: Optional[str] = None
    #: Titres des candidats écartés (contrôle visuel).
    candidats: list[str] = field(default_factory=list)


#: Repli par NOM quand le magasin n'a pas de site web renseigné.
_SITES_PAR_NOM = {
    "home depot": "https://www.homedepot.ca", "canac": "https://www.canac.ca",
    "rona": "https://www.rona.ca", "réno-dépôt": "https://www.renodepot.com",
    "reno-depot": "https://www.renodepot.com", "bmr": "https://www.bmr.ca",
    "patrick morin": "https://patrickmorin.com",
}


def module_pour_magasin(magasin: Magasin):
    """Module de parseur du magasin (par son site web, sinon par son nom)
    s'il sait chercher."""
    site = (magasin.website or "").strip() or _SITES_PAR_NOM.get((magasin.name or "").strip().lower(), "")
    if not site:
        return None
    if not site.lower().startswith(("http://", "https://")):
        site = "https://" + site
    mod = pm.parser_for(site)
    return mod if (mod is not None and hasattr(mod, "search")) else None


async def _chercher_candidat(mod, nom: str) -> tuple[Optional[Candidat], list[Candidat]]:
    """Essaie les variantes de requête ; s'arrête à la première qui donne
    un candidat acceptable. Renvoie (choisi, derniers candidats vus)."""
    vus: list[Candidat] = []
    for q in variantes(nom):
        cands = await mod.search(q)
        if not cands:
            continue
        vus = cands
        best = choisir(nom, cands)
        if best is not None:
            return best, cands
    return None, vus


async def chercher_pour_materiau(
    db,
    materiau: Materiau,
    magasins: list[Magasin],
    *,
    only_missing: bool = True,
    relever: bool = True,
) -> list[ResultatRecherche]:
    out: list[ResultatRecherche] = []
    now = datetime.now(timezone.utc)
    offres = {o.magasin_id: o for o in (materiau.offres or [])}
    for mag in magasins:
        res = ResultatRecherche(magasin_id=mag.id, magasin_name=mag.name)
        out.append(res)
        off = offres.get(mag.id)
        if only_missing and off is not None and (off.url or "").strip():
            res.statut, res.ok = "deja", True
            res.url, res.title = off.url, off.page_title
            res.price = float(off.unit_price) if off.unit_price is not None else None
            continue
        mod = module_pour_magasin(mag)
        if mod is None:
            res.statut = "non_supporte"
            res.error = "Ce magasin n'a pas de moteur de recherche branché (site web absent ou inconnu)."
            continue
        try:
            await _polite(getattr(mod, "DOMAINS", ("",))[0])
            best, cands = await _chercher_candidat(mod, materiau.name)
        except Exception as exc:  # noqa: BLE001
            res.statut, res.error = "erreur", str(exc)[:300]
            continue
        res.candidats = [c.title[:120] for c in cands[:5]]
        if best is None:
            res.statut = "aucun"
            res.error = (
                "Aucun produit du site ne correspond assez au nom du matériau "
                "(précise le nom : dimensions, format, marque)."
                if cands else "Le site ne renvoie aucun résultat pour ce nom."
            )
            continue
        if off is None:
            off = MateriauOffre(materiau_id=materiau.id, magasin_id=mag.id, source="auto")
            db.add(off)
            materiau.offres.append(off)
            offres[mag.id] = off
        off.url = best.url[:500]
        off.page_title = (best.title or "")[:255] or None
        if best.sku and not off.sku:
            off.sku = str(best.sku)[:64]
        off.note = NOTE_AUTO
        off.fetch_error = None
        # Prix donné par la recherche (souvent le prix courant du site) :
        # on le pose tout de suite, le relevé de la page affine ensuite.
        if best.price is not None and best.price > 0:
            changed = off.unit_price is None or abs(float(off.unit_price) - best.price) >= 0.005
            off.unit_price = round(best.price, 2)
            off.regular_price = round(best.regular_price, 2) if (best.on_sale and best.regular_price) else None
            off.on_sale = bool(best.on_sale and best.regular_price)
            off.sale_end = None
            off.source = "auto"
            off.observed_at = now
            if changed:
                db.add(MateriauPrixHistorique(
                    materiau_id=materiau.id, magasin_id=mag.id, unit_price=off.unit_price,
                    regular_price=off.regular_price, on_sale=off.on_sale, sale_end=None,
                    source="auto", observed_at=now, note="Recherche automatique (résultat du site)"[:255],
                ))
            res.price, res.regular_price, res.on_sale, res.method = off.unit_price, off.regular_price, off.on_sale, "recherche"
        await db.flush()
        res.ok, res.statut = True, "trouve"
        res.url, res.title, res.score = off.url, off.page_title, best.score
        if relever:
            try:
                r = await relever_offre(db, off)
                if r.ok:
                    res.price, res.regular_price, res.on_sale, res.method = r.price, r.regular_price, r.on_sale, "releve"
                elif res.price is None:
                    res.error = r.error
            except Exception as exc:  # noqa: BLE001
                if res.price is None:
                    res.error = f"Relevé de la page échoué : {exc}"[:300]
        if res.price is None:
            res.ok = False
            res.statut = "trouve_sans_prix"
    return out


async def magasins_recherchables(db, magasin_id: Optional[int] = None) -> list[Magasin]:
    stmt = select(Magasin).where(Magasin.is_active.is_(True)).order_by(Magasin.position.asc(), Magasin.id.asc())
    if magasin_id is not None:
        stmt = stmt.where(Magasin.id == magasin_id)
    else:
        stmt = stmt.where(Magasin.is_principal.is_(True))
    return [m for m in (await db.execute(stmt)).scalars().all() if module_pour_magasin(m) is not None]


async def chercher_tout(
    db,
    *,
    limit: int = 60,
    magasin_id: Optional[int] = None,
    materiau_id: Optional[int] = None,
) -> dict:
    """Comble les manques (matériau × magasin principal sans lien),
    au plus ``limit`` couples, un domaine à la fois. Flush à mesure ;
    l'appelant committe."""
    magasins = await magasins_recherchables(db, magasin_id)
    stats = {"magasins": len(magasins), "examines": 0, "trouves": 0, "aucun": 0, "erreurs": 0, "par_magasin": {}, "details": []}
    if not magasins:
        return stats
    stmt = (
        select(Materiau).where(Materiau.is_active.is_(True))
        .options(selectinload(Materiau.offres))
        .order_by(Materiau.updated_at.asc(), Materiau.id.asc())
    )
    if materiau_id is not None:
        stmt = stmt.where(Materiau.id == materiau_id)
    materiaux = list((await db.execute(stmt)).scalars().unique().all())
    # Couples à traiter, groupés par magasin (un domaine = séquentiel).
    travail: dict[int, list[Materiau]] = {}
    n = 0
    for m in materiaux:
        avec_lien = {o.magasin_id for o in m.offres if (o.url or "").strip()}
        for mag in magasins:
            if mag.id in avec_lien:
                continue
            if n >= limit:
                break
            travail.setdefault(mag.id, []).append(m)
            n += 1
    sem = asyncio.Semaphore(PARALLELISME)

    async def _run(mag: Magasin, liste: list[Materiau]) -> None:
        async with sem:
            d = stats["par_magasin"].setdefault(mag.name, {"trouves": 0, "aucun": 0, "erreurs": 0})
            for m in liste:
                rs = await chercher_pour_materiau(db, m, [mag], only_missing=True, relever=True)
                r = rs[0]
                stats["examines"] += 1
                if r.ok:
                    stats["trouves"] += 1
                    d["trouves"] += 1
                elif r.statut == "erreur":
                    stats["erreurs"] += 1
                    d["erreurs"] += 1
                    if len(stats["details"]) < 25:
                        stats["details"].append({"materiau_id": m.id, "magasin": mag.name, "error": r.error})
                    # Site indisponible / bloqué : inutile d'insister aujourd'hui.
                    if r.error and ("bloqu" in r.error or "VPS" in r.error or "HTTP 4" in r.error):
                        break
                else:
                    stats["aucun"] += 1
                    d["aucun"] += 1

    await asyncio.gather(*(_run(mag, liste) for mag in magasins for liste in [travail.get(mag.id, [])] if liste))
    log.info("Recherche prix matériaux : %s", {k: v for k, v in stats.items() if k != "details"})
    return stats


DERNIERE_RECHERCHE: dict = {"en_cours": False, "lance_a": None, "termine_a": None, "stats": None}


async def chercher_tout_en_arriere_plan(**kwargs) -> None:
    from app.db.session import AsyncSessionLocal

    if DERNIERE_RECHERCHE.get("en_cours"):
        return
    DERNIERE_RECHERCHE.update(en_cours=True, lance_a=datetime.now(timezone.utc).isoformat(), termine_a=None)
    try:
        async with AsyncSessionLocal() as db:
            stats = await chercher_tout(db, **kwargs)
            await db.commit()
        DERNIERE_RECHERCHE["stats"] = stats
    except Exception as exc:  # noqa: BLE001
        log.exception("Recherche prix matériaux en arrière-plan échouée")
        DERNIERE_RECHERCHE["stats"] = {"error": str(exc)[:300]}
    finally:
        DERNIERE_RECHERCHE.update(en_cours=False, termine_a=datetime.now(timezone.utc).isoformat())
