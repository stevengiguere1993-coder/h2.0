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
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models.materiau import Magasin, Materiau, MateriauOffre, MateriauPrixHistorique
from app.services import prix_magasins as pm
from app.services.materiaux_prix_auto import PARALLELISME, _polite, relever_offre
from app.services.prix_magasins.recherche import Candidat, choisir, requetes_mots, variantes

log = logging.getLogger(__name__)

NOTE_AUTO = "Trouvé automatiquement par recherche sur le site — vérifier que c'est le bon article."
NOTE_IA = "Apparié par IA (nom du catalogue ↔ produit du site) — vérifier que c'est le bon article."
NOTE_IA_WEB = "Trouvé par l'IA (recherche web, site bloqué ou sans résultat) — article et prix à vérifier."


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
    #: Comment le produit a été apparié au nom : regle | ia.
    appariement: str = ""
    #: Justification de l'IA quand elle a tranché.
    raison_ia: Optional[str] = None


#: Repli par NOM quand le magasin n'a pas de site web renseigné.
_SITES_PAR_NOM = {
    "home depot": "https://www.homedepot.ca", "canac": "https://www.canac.ca",
    "rona": "https://www.rona.ca", "réno-dépôt": "https://www.renodepot.com",
    "reno-depot": "https://www.renodepot.com", "bmr": "https://www.bmr.ca",
    "patrick morin": "https://patrickmorin.com",
}


def site_du_magasin(magasin: Magasin) -> str:
    site = (magasin.website or "").strip() or _SITES_PAR_NOM.get((magasin.name or "").strip().lower(), "")
    if site and not site.lower().startswith(("http://", "https://")):
        site = "https://" + site
    return site


def module_pour_magasin(magasin: Magasin):
    """Module de parseur du magasin (par son site web, sinon par son nom)
    s'il sait chercher."""
    site = site_du_magasin(magasin)
    if not site:
        return None
    mod = pm.parser_for(site)
    return mod if (mod is not None and hasattr(mod, "search")) else None


def _meme_site(magasin: Magasin, url: str) -> bool:
    """Le lien retenu doit appartenir au site DU magasin (rona.ca pour
    Rona, pas pour Réno-Dépôt qui partage le module)."""
    a, b = pm.domain_of(site_du_magasin(magasin)), pm.domain_of(url)
    return bool(a) and bool(b) and (a == b or b.endswith("." + a))


MAX_REQUETES = 7
#: Résultats demandés pour la requête « par mot » (toutes les grandeurs
#: d'un produit : il en faut plus que 10).
LIMITE_MOT = 40
#: Score de règles « sûr » : accepté sans l'avis de l'IA.
SCORE_SUR = 0.999


def _err(exc: BaseException) -> str:
    """Message d'erreur jamais vide (un ReadTimeout httpx s'imprime « »)."""
    return (str(exc).strip() or exc.__class__.__name__)[:300]


async def _chercher_candidat(mod, nom: str) -> tuple[Optional[Candidat], list[Candidat], str, Optional[str]]:
    """Cherche le produit sur le site, dans l'ordre :

    1. requêtes réécrites par l'IA (si configurée) ;
    2. variantes du nom tel quel ;
    3. requête « PAR MOT » (le produit seul, ex. « epinette » pour
       « épinette 2x6 », avec plus de résultats) : le site renvoie toutes
       les grandeurs et le notateur retient celle dont les nombres
       correspondent.

    À chaque requête le notateur par règles tranche. Sans IA, le premier
    candidat ≥ seuil est retenu. Avec l'IA, on arrête les requêtes dès
    qu'un candidat ≥ seuil existe et c'est l'IA qui confirme (ou corrige,
    ou refuse) parmi tout ce qui a été vu : elle lit les titres (« adaptateur
    de conduit PVC » n'est pas un adaptateur de plomberie) ; si elle ne
    répond pas, le choix des règles reste. Renvoie (choisi, candidats vus,
    appariement « regle » | « ia » | « », raison IA)."""
    from app.services.prix_magasins import appariement_ia as ia

    domaine = getattr(mod, "DOMAINS", ("",))[0]
    requetes: list[tuple[str, int]] = []

    def _ajouter(q: Optional[str], limite: int) -> None:
        q = re.sub(r"\s+", " ", q or "").strip()
        if q and q.lower() not in {x.lower() for x, _ in requetes}:
            requetes.append((q, limite))

    for q in await ia.requetes_pour(nom):
        _ajouter(q, 20)
    for q in variantes(nom):
        _ajouter(q, 20)
    for q in requetes_mots(nom):
        _ajouter(q, LIMITE_MOT)

    vus: dict[str, Candidat] = {}
    reserve: Optional[Candidat] = None
    premier = True
    for q, limite in requetes[:MAX_REQUETES]:
        if not premier:
            await _polite(domaine)
        premier = False
        try:
            cands = await mod.search(q, limit=limite)
        except TypeError:
            cands = await mod.search(q)
        if not cands:
            continue
        for c in cands:
            vus.setdefault(c.url, c)
        best = choisir(nom, cands)
        if best is None:
            continue
        if not ia.disponible():
            return best, cands, "regle", None
        if reserve is None or best.score > reserve.score:
            reserve = best
        if reserve.score >= SCORE_SUR:
            break  # tout y est : l'IA confirme, inutile de chercher plus
    tous = list(vus.values())
    if tous and ia.disponible():
        # Le choix des règles passe en tête de liste (l'IA n'en lit que
        # les premiers), le reste dans l'ordre de pertinence des sites.
        ordre = ([reserve] if reserve is not None else []) + [c for c in tous if c is not reserve]
        best, conf, raison, repondu = await ia.choisir_parmi(nom, ordre)
        if best is not None:
            if best is reserve:
                return best, tous, "regle", raison
            best.score = conf
            return best, tous, "ia", raison
        if repondu:
            # L'IA a lu les titres et dit « aucun » : pas de prix plutôt
            # qu'un mauvais prix (le nom reste à préciser).
            return None, tous, "", raison
    if reserve is not None:
        return reserve, tous, "regle", None
    return None, tous, "", None


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
        best, cands, appariement, raison_ia = None, [], "", None
        erreur_site: Optional[str] = None
        try:
            await _polite(getattr(mod, "DOMAINS", ("",))[0])
            best, cands, appariement, raison_ia = await _chercher_candidat(mod, materiau.name)
        except Exception as exc:  # noqa: BLE001
            erreur_site = _err(exc)
        if best is not None and not _meme_site(mag, best.url):
            best = None  # lien d'un autre site (Réno-Dépôt ↔ Rona…)
        if best is None:
            # Repli : l'IA cherche sur le web (Gemini + Google Search) la
            # page produit DU site — site bloqué (Cloudflare), sans
            # résultat ou sans correspondance (Phil 2026-10-01).
            from app.services.prix_magasins import appariement_ia as ia

            web = await ia.rechercher_web(materiau.name, site_du_magasin(mag), mag.name)
            if web is not None and _meme_site(mag, web.url):
                best, appariement, raison_ia = web, "ia_web", (web.extra or {}).get("raison")
        res.candidats = [c.title[:120] for c in cands[:5]]
        res.appariement, res.raison_ia = appariement, raison_ia
        if best is None:
            if erreur_site:
                res.statut, res.error = "erreur", erreur_site
                continue
            res.statut = "aucun"
            res.error = (
                "Aucun produit du site ne correspond assez au nom du matériau "
                "(précise le nom : dimensions, format, marque)."
                if cands else "Le site ne renvoie aucun résultat pour ce nom."
            )
            continue
        nouvelle = off is None
        if nouvelle:
            off = MateriauOffre(materiau_id=materiau.id, magasin_id=mag.id, source="auto")
            db.add(off)
            materiau.offres.append(off)
            offres[mag.id] = off
        # Sauvegarde de l'état précédent : si ni la recherche ni le relevé
        # ne donnent de prix, on remet l'offre comme elle était (pas de
        # lien « trouvé automatiquement » à côté d'un vieux prix manuel).
        avant = {k: getattr(off, k) for k in ("url", "sku", "page_title", "note", "fetch_error")}
        url_change = (off.url or "") != best.url[:500]
        off.url = best.url[:500]
        off.page_title = (best.title or "")[:255] or None
        if url_change or not off.sku:
            off.sku = (str(best.sku)[:64] if best.sku else None)
        note_avant = (avant["note"] or "").strip()
        note_auto = NOTE_IA_WEB if appariement == "ia_web" else (NOTE_IA if appariement == "ia" else NOTE_AUTO)
        note_avant = note_avant.replace(NOTE_AUTO, "").replace(NOTE_IA, "").strip(" ·")
        off.note = (note_auto if not note_avant else f"{note_avant} · {note_auto}")[:255]
        off.fetch_error = None
        prix_recherche = round(best.price, 2) if (best.price is not None and best.price > 0) else None
        res.url, res.title, res.score = off.url, off.page_title, best.score
        await db.flush()
        # 1) relevé de la page produit (source de vérité) quand la
        # recherche n'a pas donné de prix — sinon on garde celui de la
        # recherche (le relevé quotidien affinera) : un aller-retour de
        # moins par article, surtout via le VPS ; 2) historique écrit une
        # seule fois.
        r = None
        if relever and prix_recherche is None:
            try:
                r = await relever_offre(db, off)
            except Exception as exc:  # noqa: BLE001
                r = None
                res.error = f"Relevé de la page échoué : {exc}"[:300]
        if r is not None and r.ok:
            res.price, res.regular_price, res.on_sale, res.method = r.price, r.regular_price, r.on_sale, "releve"
        elif prix_recherche is not None:
            changed = off.unit_price is None or abs(float(off.unit_price) - prix_recherche) >= 0.005
            off.unit_price = prix_recherche
            off.regular_price = round(best.regular_price, 2) if (best.on_sale and best.regular_price) else None
            off.on_sale = bool(best.on_sale and best.regular_price)
            off.sale_end = None
            off.source = "auto"
            off.observed_at = now
            if changed:
                db.add(MateriauPrixHistorique(
                    materiau_id=materiau.id, magasin_id=mag.id, unit_price=off.unit_price,
                    regular_price=off.regular_price, on_sale=off.on_sale, sale_end=None,
                    source="auto", observed_at=now,
                    note=("Trouvé par l'IA (recherche web)" if appariement == "ia_web" else "Recherche automatique (résultat du site)")[:255],
                ))
            res.price, res.regular_price, res.on_sale, res.method = off.unit_price, off.regular_price, off.on_sale, ("ia_web" if appariement == "ia_web" else "recherche")
            if r is not None and not r.ok:
                res.error = r.error  # information : la page n'a pas pu être relue
        else:
            if r is not None and not r.ok and not res.error:
                res.error = r.error
            if nouvelle:
                # Lien gardé (le relevé quotidien réessaiera), sans prix.
                res.ok, res.statut = False, "trouve_sans_prix"
            else:
                for k, v in avant.items():
                    setattr(off, k, v)
                res.statut = "trouve_sans_prix"
                res.url, res.title = avant["url"], avant["page_title"]
            await db.flush()
            continue
        await db.flush()
        res.ok, res.statut = True, "trouve"
    return out


async def magasins_recherchables(db, magasin_id: Optional[int] = None) -> list[Magasin]:
    stmt = select(Magasin).where(Magasin.is_active.is_(True)).order_by(Magasin.position.asc(), Magasin.id.asc())
    if magasin_id is not None:
        stmt = stmt.where(Magasin.id == magasin_id)
    else:
        stmt = stmt.where(Magasin.is_principal.is_(True))
    return [m for m in (await db.execute(stmt)).scalars().all() if module_pour_magasin(m) is not None]


async def _couples_a_chercher(
    db, magasins: list[Magasin], *, limit: int, materiau_id: Optional[int], max_age_days: Optional[float],
) -> dict[int, list[int]]:
    """magasin_id → ids de matériaux sans lien chez ce magasin. Les
    matériaux jamais cherchés d'abord, puis les plus anciens ; ceux
    cherchés depuis moins de ``max_age_days`` jours sont sautés (le cron
    ne re-cherche pas chaque jour les mêmes introuvables)."""
    stmt = (
        select(Materiau).where(Materiau.is_active.is_(True))
        .options(selectinload(Materiau.offres))
        .order_by(Materiau.prix_recherche_at.asc().nulls_first(), Materiau.updated_at.asc(), Materiau.id.asc())
    )
    if materiau_id is not None:
        stmt = stmt.where(Materiau.id == materiau_id)
    materiaux = list((await db.execute(stmt)).scalars().unique().all())
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)) if max_age_days else None
    travail: dict[int, list[int]] = {}
    n = 0
    for m in materiaux:
        if cutoff is not None and m.prix_recherche_at is not None:
            pra = m.prix_recherche_at if m.prix_recherche_at.tzinfo else m.prix_recherche_at.replace(tzinfo=timezone.utc)
            if pra > cutoff:
                continue
        avec_lien = {o.magasin_id for o in m.offres if (o.url or "").strip()}
        for mag in magasins:
            if mag.id in avec_lien:
                continue
            if n >= limit:
                break
            travail.setdefault(mag.id, []).append(m.id)
            n += 1
    return travail


async def _chercher_un_couple(db, materiau_id: int, mag: Magasin) -> ResultatRecherche:
    m = (await db.execute(
        select(Materiau).where(Materiau.id == materiau_id).options(selectinload(Materiau.offres))
    )).scalar_one_or_none()
    if m is None:
        return ResultatRecherche(magasin_id=mag.id, magasin_name=mag.name, statut="erreur", error="matériau disparu")
    m.prix_recherche_at = datetime.now(timezone.utc)
    rs = await chercher_pour_materiau(db, m, [mag], only_missing=True, relever=True)
    return rs[0]


async def chercher_tout(
    db,
    *,
    limit: int = 60,
    magasin_id: Optional[int] = None,
    materiau_id: Optional[int] = None,
    max_age_days: Optional[float] = None,
    session_factory=None,
    stats_live: Optional[dict] = None,
) -> dict:
    """Comble les manques (matériau × magasin principal sans lien), au
    plus ``limit`` couples.

    - ``stats_live`` : dict mis à jour EN DIRECT à chaque couple (compteurs,
      total prévu, dernier résultat) — c'est ce que lit
      ``GET /materiaux/prix/chercher/etat`` pendant la course.

    - ``session_factory`` (prod : ``AsyncSessionLocal``) : un magasin par
      tâche, chacune avec SA session et un commit par couple — une
      AsyncSession ne supporte pas plusieurs tâches en parallèle, et un
      commit par couple évite une transaction ouverte pendant toute la
      course (appels VPS lents) ou un lot entier perdu sur une erreur.
    - sans fabrique (tests) : séquentiel sur ``db``, l'appelant committe.
    """
    magasins = await magasins_recherchables(db, magasin_id)
    stats = stats_live if stats_live is not None else {}
    stats.update({"magasins": len(magasins), "total": 0, "examines": 0, "trouves": 0, "aucun": 0, "erreurs": 0, "par_magasin": {}, "details": [], "dernier": None})
    if not magasins:
        return stats
    travail = await _couples_a_chercher(db, magasins, limit=limit, materiau_id=materiau_id, max_age_days=max_age_days)
    stats["total"] = sum(len(ids) for ids in travail.values())
    sem = asyncio.Semaphore(PARALLELISME)

    def _compter(mag: Magasin, materiau_id_: int, r: ResultatRecherche) -> bool:
        """Met à jour les stats ; True = arrêter ce magasin aujourd'hui."""
        d = stats["par_magasin"].setdefault(mag.name, {"trouves": 0, "aucun": 0, "erreurs": 0})
        stats["examines"] += 1
        stats["dernier"] = {
            "magasin": mag.name, "materiau_id": materiau_id_, "statut": r.statut, "appariement": r.appariement,
            "title": (r.title or "")[:120] or None, "price": r.price, "error": (r.error or "")[:160] or None,
            "a": datetime.now(timezone.utc).isoformat(),
        }
        if r.ok:
            stats["trouves"] += 1
            d["trouves"] += 1
        elif r.statut == "erreur":
            stats["erreurs"] += 1
            d["erreurs"] += 1
            if len(stats["details"]) < 25:
                stats["details"].append({"materiau_id": materiau_id_, "magasin": mag.name, "error": r.error})
            # Site indisponible / bloqué : inutile d'insister aujourd'hui.
            return bool(r.error and ("bloqu" in r.error or "VPS" in r.error or "HTTP 4" in r.error))
        else:
            stats["aucun"] += 1
            d["aucun"] += 1
        return False

    async def _run_session(mag: Magasin, ids: list[int]) -> None:
        async with sem:
            async with session_factory() as s:
                for mid in ids:
                    try:
                        r = await _chercher_un_couple(s, mid, mag)
                        await s.commit()
                    except IntegrityError:
                        # Offre créée entre-temps par une autre course : on passe.
                        await s.rollback()
                        continue
                    except Exception as exc:  # noqa: BLE001
                        await s.rollback()
                        r = ResultatRecherche(magasin_id=mag.id, magasin_name=mag.name, statut="erreur", error=_err(exc))
                    if _compter(mag, mid, r):
                        break

    if session_factory is not None:
        await asyncio.gather(*(_run_session(mag, ids) for mag in magasins for ids in [travail.get(mag.id, [])] if ids))
    else:
        for mag in magasins:
            for mid in travail.get(mag.id, []):
                try:
                    r = await _chercher_un_couple(db, mid, mag)
                    await db.flush()
                except IntegrityError:
                    await db.rollback()
                    continue
                if _compter(mag, mid, r):
                    break
    log.info("Recherche prix matériaux : %s", {k: v for k, v in stats.items() if k != "details"})
    return stats


DERNIERE_RECHERCHE: dict = {"en_cours": False, "lance_a": None, "termine_a": None, "stats": None}

_SCRAPER_ETAT: dict = {"verifie_a": None, "en_ligne": None, "detail": None}


async def etat_scraper_vps(max_age_s: float = 60.0) -> dict:
    """Ping du VPS de scraping (Rona / BMR) — ``/health`` avec un court
    délai, mis en cache ``max_age_s`` pour ne pas marteler le VPS à chaque
    rafraîchissement de la page catalogue."""
    import httpx

    from app.integrations.scraping_proxy import VPS_KEY, VPS_URL

    now = datetime.now(timezone.utc)
    v = _SCRAPER_ETAT.get("verifie_a")
    if v and (now - datetime.fromisoformat(v)).total_seconds() < max_age_s:
        return dict(_SCRAPER_ETAT)
    en_ligne, detail = False, None
    if not VPS_URL:
        detail = "SCRAPING_VPS_URL non défini"
    else:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=4.0)) as client:
                r = await client.get(f"{VPS_URL}/health")
            en_ligne = r.status_code == 200
            detail = None if en_ligne else f"HTTP {r.status_code}"
            if en_ligne and not VPS_KEY:
                en_ligne, detail = False, "SCRAPING_VPS_KEY non défini sur l'API"
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)[:160] or exc.__class__.__name__
    _SCRAPER_ETAT.update(verifie_a=now.isoformat(), en_ligne=en_ligne, detail=detail, url=VPS_URL)
    return dict(_SCRAPER_ETAT)


async def chercher_tout_en_arriere_plan(**kwargs) -> None:
    """Course complète avec une session par magasin (voir chercher_tout).
    Un seul run à la fois par processus (bouton, route, cron)."""
    from app.db.session import AsyncSessionLocal

    if DERNIERE_RECHERCHE.get("en_cours"):
        return
    live: dict = {}
    DERNIERE_RECHERCHE.update(en_cours=True, lance_a=datetime.now(timezone.utc).isoformat(), termine_a=None, stats=live)
    try:
        async with AsyncSessionLocal() as db:
            stats = await chercher_tout(db, session_factory=AsyncSessionLocal, stats_live=live, **kwargs)
        DERNIERE_RECHERCHE["stats"] = stats
    except Exception as exc:  # noqa: BLE001
        log.exception("Recherche prix matériaux en arrière-plan échouée")
        DERNIERE_RECHERCHE["stats"] = {"error": str(exc)[:300]}
    finally:
        DERNIERE_RECHERCHE.update(en_cours=False, termine_a=datetime.now(timezone.utc).isoformat())


async def chercher_tout_pour_cron(*, limit: int = 40, max_age_days: float = 7) -> dict:
    """Entrée du cron quotidien : mêmes garde-fous que le bouton (un run
    à la fois), quota borné, matériaux déjà cherchés récemment sautés."""
    if DERNIERE_RECHERCHE.get("en_cours"):
        return {"skipped": "recherche_deja_en_cours"}
    await chercher_tout_en_arriere_plan(limit=limit, max_age_days=max_age_days)
    return dict(DERNIERE_RECHERCHE.get("stats") or {})
