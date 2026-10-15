"""Registre des courtiers — recherche automatique du courriel (Phil
2026-10-14 : « il faut que ça soit automatique, trouver le courriel d'un
courtier est très facile »).

On fait en machine ce qu'un humain fait : chercher « Prénom Nom courtier
immobilier Agence » sur le web, ouvrir la page de son agence ou son site,
lire le courriel, vérifier qu'il correspond au nom, et l'écrire dans la
fiche AVEC la source et un niveau de confiance :

- ``verifie``   : le courriel correspond au nom ET a été lu sur une page
                  où le nom du courtier apparaît ;
- ``probable``  : le courriel correspond au nom (initiale + nom, prénom.nom…)
                  mais n'a pas pu être relu sur une page ;
- rien          : aucun courriel qui corresponde au nom → la fiche reste
                  vide, les candidats écartés (info@, admin@…) sont notés.

Sources, dans l'ordre : Gemini avec recherche Google (si clé), puis
DuckDuckGo et Bing (HTML direct), puis le VPS de scraping (Playwright)
quand un moteur ou une page nous bloque. Chaque fonction réseau est un
point d'entrée unique (``_http_get``) remplaçable dans les tests.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.prospection_courtier import ProspectionCourtier

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_TIMEOUT_PAGE_S = 12.0
_MAX_PAGE_BYTES = 400_000
_MAX_PAGES_PAR_COURTIER = 6
_BUDGET_PAR_COURTIER_S = 75.0

_MAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
#: Parties locales génériques : jamais le courriel d'une personne.
_LOCAUX_GENERIQUES = {
    "info", "contact", "admin", "administration", "bureau", "office", "reception",
    "ventes", "sales", "noreply", "no-reply", "support", "service", "courtier",
    "courtiers", "agence", "equipe", "team", "hello", "bonjour", "marketing",
    "webmaster", "communications", "rh", "hr", "jobs", "careers", "privacy",
    "location", "rental", "comptabilite", "accounting", "media", "presse",
}
#: Domaines où l'on ne trouve jamais le courriel d'un courtier (ou qui
#: bloquent les robots) : on ne les ouvre pas.
_DOMAINES_EXCLUS = (
    "centris.ca", "duproprio.com", "realtor.ca", "facebook.com", "instagram.com",
    "linkedin.com", "youtube.com", "twitter.com", "x.com", "pinterest.", "google.",
    "wikipedia.org", "tiktok.com", "yelp.", "pagesjaunes.ca", "yellowpages.ca",
    "oaciq.com", "kijiji.ca", "lespac.com", "zillow.com", "apple.com", "bing.com",
    "duckduckgo.com", "vertexaisearch.cloud.google.com",
)
#: Faux positifs fréquents dans le HTML (images, polices, placeholders).
_DOMAINES_COURRIEL_BIDON = (
    "example.", "sentry.", "wixpress.", "w3.org", "schema.org", "2x.png", ".png",
    ".jpg", ".jpeg", ".gif", ".svg", ".webp", "domain.com", "email.com", "test.com",
    "yoursite", "votresite", "sentry-next", "mailchimp", "googlemail",
)
_PARTICULES = {"de", "du", "des", "la", "le", "les", "van", "von", "st", "ste", "d"}
#: Annuaires de données de contacts (souvent devinés) : on garde le
#: candidat mais jamais au rang « vérifié ».
_DOMAINES_DONNEES_CONTACT = (
    "contactout.", "rocketreach.", "signalhire.", "zoominfo.", "apollo.io", "lusha.",
    "hunter.io", "kaspr.", "snov.io", "leadiq.", "clearbit.", "adapt.io",
)
#: Sites de recherche de personnes (surtout américains) : courriels de
#: n'importe qui portant le même nom → jamais ouverts, extraits ignorés.
_DOMAINES_RECHERCHE_PERSONNES = (
    "veripages.", "spokeo.", "whitepages.", "radaris.", "fastpeoplesearch.",
    "truepeoplesearch.", "peoplefinders.", "beenverified.", "intelius.", "nuwber.",
    "clustrmaps.", "cyberbackgroundchecks.", "mylife.", "publicdatausa.", "411.com",
    "411.ca", "canada411.", "peekyou.", "pipl.", "thatsthem.", "usphonebook.",
    "zabasearch.", "searchpeoplefree.", "locatefamily.", "findglocal.", "cybo.",
    "yellowpages.", "pagesjaunes.", "infobel.", "hotfrog.", "cylex.", "opendi.",
)
#: Webmails : n'importe qui peut y créer « cote123@ » — on n'accepte que
#: prénom + nom ou initiale + nom.
_DOMAINES_WEBMAIL = (
    "gmail.", "hotmail.", "yahoo.", "outlook.", "live.", "icloud.", "videotron.",
    "bell.net", "sympatico.", "me.com", "aol.", "protonmail.", "proton.me", "msn.",
)
_MOTS_IGNORES = {
    "inc", "courtier", "courtiers", "immobilier", "immobiliere", "immobilière",
    "residentiel", "résidentiel", "commercial", "agree", "agréé", "agréée", "equipe",
    "équipe", "groupe", "team", "me", "m", "mme",
}


# ─── Nom → jetons ─────────────────────────────────────────────────────


def _sans_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    )


def tokens_nom(nom: str) -> list[str]:
    """« Marc-André Knot » → ['marc', 'andre', 'knot'] ; « Denis Gallico,
    Maxime Gerard » → jetons de la PREMIÈRE personne (avant la virgule)."""
    premier = (nom or "").split(",")[0]
    premier = re.sub(r"\(.*?\)", " ", premier)
    s = _sans_accents(premier).lower()
    jetons = [t for t in re.split(r"[^a-z]+", s) if len(t) >= 2]
    return [t for t in jetons if t not in _MOTS_IGNORES and t not in _PARTICULES]


def _jetons_agence(agence: Optional[str]) -> list[str]:
    s = _sans_accents(agence or "").lower()
    return [t for t in re.split(r"[^a-z0-9]+", s) if len(t) >= 4 and t not in _MOTS_IGNORES]


def courriel_propre(c: Optional[str]) -> Optional[str]:
    """Normalise et écarte les faux positifs ; None si invalide."""
    if not c:
        return None
    m = _MAIL_RE.search(str(c))
    if not m:
        return None
    v = m.group(0).strip().lower().strip(".")
    if any(b in v for b in _DOMAINES_COURRIEL_BIDON):
        return None
    local, _, domaine = v.partition("@")
    if not local or "." not in domaine or len(v) > 120:
        return None
    if domaine.endswith("centris.ca") or domaine.endswith("duproprio.com"):
        return None
    return v


def score_courriel(courriel: str, nom: str, agence: Optional[str] = None) -> tuple[int, str]:
    """0-100 : à quel point le courriel ressemble au courtier.
    ≥ 55 = correspond au nom (on l'accepte) ; < 55 = écarté."""
    local, _, domaine = courriel.lower().partition("@")
    local_a = re.sub(r"[^a-z]", "", _sans_accents(local))
    jetons = tokens_nom(nom)
    if not jetons:
        return 0, "nom vide"
    prenom = jetons[0]
    nom_famille = jetons[-1] if len(jetons) > 1 else ""
    prenoms = jetons[:-1] if len(jetons) > 1 else jetons  # prénom (composé)
    score = 0
    raisons: list[str] = []
    if local_a in _LOCAUX_GENERIQUES or local in _LOCAUX_GENERIQUES:
        return 10, "adresse générique"
    nom_ok = len(nom_famille) >= 3 and nom_famille in local_a
    prenom_ok = len(prenom) >= 3 and prenom in local_a
    prenom_compose_ok = len(prenoms) >= 2 and all(len(x) >= 3 and x in local_a for x in prenoms)
    initiale_nom = bool(nom_famille) and bool(
        re.match(rf"^{re.escape(prenom[0])}[._-]?{re.escape(nom_famille)}", local_a)
        or local_a == prenom[0] + nom_famille
    )
    if nom_ok and prenom_ok:
        score += 85
        raisons.append("prénom et nom")
    elif initiale_nom:
        score += 70
        raisons.append("initiale et nom")
    elif nom_ok:
        score += 60
        raisons.append("nom de famille")
    elif prenom_compose_ok:
        score += 55
        raisons.append("prénom composé")
    elif prenom_ok and len(nom_famille) >= 4 and nom_famille in _sans_accents(domaine).lower():
        # daniel@groupe-immosauve.com pour Daniel Sauvé : le nom est le domaine.
        score += 60
        raisons.append("prénom, nom dans le domaine")
    elif prenom_ok and len(prenom) >= 5:
        score += 40
        raisons.append("prénom seulement")
    jd = _jetons_agence(agence)
    dom_a = _sans_accents(domaine).lower()
    bonus_domaine = False
    if jd and any(j in dom_a for j in jd):
        score += 10
        bonus_domaine = True
        raisons.append("domaine de l'agence")
    if any(t in dom_a for t in jetons if len(t) >= 4):
        score += 10
        bonus_domaine = True
        raisons.append("domaine au nom du courtier")
    fort = raisons and raisons[0] in ("prénom et nom", "initiale et nom")
    if any(w in dom_a for w in _DOMAINES_WEBMAIL) and not fort:
        # Webmail avec un nom de famille seul : trop incertain.
        score = min(score, 45)
        raisons.append("webmail sans prénom")
    elif raisons and raisons[0] == "nom de famille" and len(nom_famille) < 5 and not bonus_domaine:
        # Nom court (Côté, Roy, Gagné…) seul sur un domaine quelconque.
        score = min(score, 45)
        raisons.append("nom court sans domaine d'agence")
    return min(score, 100), ", ".join(raisons) or "aucune correspondance"


def _domaine_exclu(url: str) -> bool:
    try:
        h = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return True
    return not h or any(d in h for d in _DOMAINES_EXCLUS) or any(
        d in h for d in _DOMAINES_RECHERCHE_PERSONNES
    )


def _source_douteuse(source: str) -> bool:
    """Extrait ou page d'un site de recherche de personnes : on n'en tire
    aucun candidat."""
    bas = (source or "").lower()
    return any(d in bas for d in _DOMAINES_RECHERCHE_PERSONNES)


_OBFUSCATIONS = (
    (re.compile(r"\s*[\[\({]\s*(?:at|arobas|arobase)\s*[\]\)}]\s*", re.IGNORECASE), "@"),
    (re.compile(r"\s+(?:at|arobas|arobase)\s+", re.IGNORECASE), "@"),
    (re.compile(r"\s*[\[\({]\s*(?:dot|point)\s*[\]\)}]\s*", re.IGNORECASE), "."),
    (re.compile(r"&#64;|&commat;|%40", re.IGNORECASE), "@"),
)


def deobfusquer(texte: str) -> str:
    """« prenom [at] agence [dot] ca » → « prenom@agence.ca »."""
    s = texte or ""
    for rx, rempl in _OBFUSCATIONS:
        s = rx.sub(rempl, s)
    return s


def extraire_courriels(texte: str, mailtos: Optional[list[str]] = None) -> list[str]:
    """Courriels d'un texte / d'une liste de liens mailto, dédoublonnés,
    nettoyés, ordre d'apparition."""
    vus: list[str] = []
    texte = deobfusquer(texte or "")
    for brut in list(mailtos or []) + _MAIL_RE.findall(texte):
        c = courriel_propre(brut.replace("mailto:", "").split("?")[0])
        if c and c not in vus:
            vus.append(c)
    return vus


# ─── Réseau (points d'entrée uniques, remplacés dans les tests) ────────


async def _http_get(url: str, *, params: Optional[dict] = None, timeout: float = _TIMEOUT_PAGE_S) -> tuple[int, str]:
    """GET avec un User-Agent de navigateur ; renvoie (statut, texte)."""
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": UA, "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.7"}
    ) as client:
        r = await client.get(url, params=params)
        texte = r.text
        if len(texte) > _MAX_PAGE_BYTES:
            texte = texte[:_MAX_PAGE_BYTES]
        return r.status_code, texte


def _soup(html: str):
    from bs4 import BeautifulSoup  # type: ignore

    return BeautifulSoup(html or "", "html.parser")


_BLOCS_TEXTE = ["p", "li", "td", "th", "div", "h1", "h2", "h3", "h4", "h5", "h6",
                "a", "address", "section", "article", "body"]
_DEBUT_COURRIEL_RE = re.compile(r"^[\w.+-]*@[\w.-]+")
_FIN_MOT_RE = re.compile(r"[\w.+-]$")


def texte_colle_par_bloc(soup) -> str:
    """Texte de la page où deux morceaux d'un MÊME bloc sont recollés
    quand le second commence par « …@ » (« rosibe</span>l@agence.com »
    → « rosibel@agence.com »). Ne sert qu'à l'extraction des courriels."""
    out: list[str] = []
    dernier_bloc = None
    for s in soup.find_all(string=True):
        txt = str(s).strip()
        if not txt:
            continue
        parent = s.find_parent(_BLOCS_TEXTE)
        bloc = id(parent) if parent is not None else None
        if (
            out and bloc is not None and bloc == dernier_bloc
            and _FIN_MOT_RE.search(out[-1])
            and (_DEBUT_COURRIEL_RE.match(txt) or out[-1].endswith("@"))
        ):
            out[-1] = out[-1] + txt
        else:
            out.append(txt)
        dernier_bloc = bloc
    return " ".join(out)


def parser_duckduckgo(html: str) -> list[dict]:
    """Résultats de html.duckduckgo.com → [{url, titre, extrait}]."""
    out: list[dict] = []
    soup = _soup(html)
    for res in soup.select(".result"):
        a = res.select_one("a.result__a") or res.select_one("a[href]")
        if not a:
            continue
        href = a.get("href") or ""
        if "uddg=" in href:
            q = parse_qs(urlparse(href).query)
            href = (q.get("uddg") or [href])[0]
        if not href.startswith("http"):
            continue
        sn = res.select_one(".result__snippet")
        out.append({
            "url": href,
            "titre": a.get_text(" ", strip=True),
            "extrait": sn.get_text(" ", strip=True) if sn else "",
        })
    return out


def decoder_redirection_bing(href: str) -> str:
    """bing.com/ck/a?…&u=a1<base64 de l'URL> → l'URL réelle."""
    if "bing.com/ck/a" not in (href or ""):
        return href
    try:
        u = (parse_qs(urlparse(href).query).get("u") or [""])[0]
        if u.startswith("a1"):
            u = u[2:]
        u += "=" * (-len(u) % 4)
        reel = base64.urlsafe_b64decode(u.encode("ascii")).decode("utf-8", "ignore")
        return reel if reel.startswith("http") else href
    except Exception:  # noqa: BLE001
        return href


def decoder_redirection(href: str) -> str:
    """Lien de moteur → URL réelle : DuckDuckGo (/l/?uddg=…) et Bing
    (ck/a?…&u=a1<base64>)."""
    h = href or ""
    if "duckduckgo.com/l/" in h and "uddg=" in h:
        q = parse_qs(urlparse(h).query)
        reel = (q.get("uddg") or [""])[0]
        return reel if reel.startswith("http") else h
    return decoder_redirection_bing(h)


def parser_bing(html: str) -> list[dict]:
    """Résultats de bing.com/search → [{url, titre, extrait}]."""
    out: list[dict] = []
    soup = _soup(html)
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a[href]")
        if not a:
            continue
        href = decoder_redirection_bing(a.get("href") or "")
        if not href.startswith("http"):
            continue
        p = li.select_one(".b_caption p") or li.select_one("p")
        out.append({
            "url": href,
            "titre": a.get_text(" ", strip=True),
            "extrait": p.get_text(" ", strip=True) if p else "",
        })
    return out


def _bloque(html: str, statut: int) -> bool:
    bas = (html or "").lower()
    return statut in (202, 403, 429, 503) or "anomaly-modal" in bas or "captcha" in bas[:5000]


def resultats_pertinents(resultats: list[dict], jetons: list[str]) -> list[dict]:
    """Garde les résultats qui parlent du courtier : un jeton du nom
    (≥ 3 lettres) dans le titre, l'extrait ou l'URL. Un moteur qui nous
    prend pour un robot renvoie des pages bidon (NFL, boutiques…) : sans
    jeton, le lot est jugé vide."""
    jet = [t for t in jetons if len(t) >= 3]
    if not jet:
        return resultats
    out = []
    for r in resultats:
        bas = _sans_accents(
            " ".join(str(r.get(k) or "") for k in ("titre", "extrait", "url"))
        ).lower()
        if any(t in bas for t in jet):
            out.append(r)
    return out


async def _via_google_cse(requete: str) -> list[dict]:
    """Google Programmable Search (JSON API) — le plus fiable, si Phil a
    configuré GOOGLE_CSE_KEY et GOOGLE_CSE_ID (100 requêtes/jour gratuites)."""
    import os

    cle = (getattr(settings, "google_cse_key", None) or os.getenv("GOOGLE_CSE_KEY") or "").strip()
    cx = (getattr(settings, "google_cse_id", None) or os.getenv("GOOGLE_CSE_ID") or "").strip()
    if not cle or not cx:
        return []
    statut, texte = await _http_get(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": cle, "cx": cx, "q": requete, "num": 8, "hl": "fr", "gl": "ca"},
        timeout=20.0,
    )
    if statut >= 400:
        log.info("Google CSE HTTP %s : %s", statut, (texte or "")[:200])
        return []
    data = json.loads(texte or "{}")
    return [
        {"url": it.get("link") or "", "titre": it.get("title") or "", "extrait": it.get("snippet") or ""}
        for it in (data.get("items") or []) if (it.get("link") or "").startswith("http")
    ]


async def _via_vps(requete: str, jetons: Optional[list[str]] = None) -> list[dict]:
    from app.integrations import scraping_proxy

    if not scraping_proxy.vps_available():
        return []
    res = await scraping_proxy.scrape_web_search(
        requete, must_contain=[t for t in (jetons or []) if len(t) >= 3]
    )
    return [
        {"url": decoder_redirection(r.get("url") or ""), "titre": r.get("titre") or r.get("title") or "",
         "extrait": r.get("extrait") or r.get("snippet") or ""}
        for r in (res or []) if (r.get("url") or "").startswith("http")
    ]


#: Ordre par défaut des moteurs web : Google (si configuré), le navigateur
#: du VPS (vraie session, pas flairé comme robot), puis le direct.
MOTEURS_WEB_DEFAUT = ("google", "vps", "duckduckgo", "bing")


async def rechercher_web(
    requete: str, *, moteurs: tuple[str, ...] = MOTEURS_WEB_DEFAUT,
    jetons: Optional[list[str]] = None, journal: Optional[list[str]] = None,
) -> list[dict]:
    """Résultats web [{url, titre, extrait}] pertinents, du premier moteur
    qui en donne : google (API, si clé) → vps (navigateur) → duckduckgo →
    bing (HTML direct)."""
    for moteur in moteurs:
        try:
            res: list[dict] = []
            if moteur == "google":
                res = await _via_google_cse(requete)
            elif moteur == "vps":
                res = await _via_vps(requete, jetons)
            elif moteur == "duckduckgo":
                statut, html = await _http_get(
                    "https://html.duckduckgo.com/html/", params={"q": requete, "kl": "ca-fr"},
                    timeout=8.0,
                )
                res = [] if _bloque(html, statut) else parser_duckduckgo(html)
            elif moteur == "bing":
                statut, html = await _http_get(
                    "https://www.bing.com/search", params={"q": requete, "setlang": "fr", "cc": "CA"},
                    timeout=8.0,
                )
                res = [] if _bloque(html, statut) else parser_bing(html)
            else:
                continue
            for r in res:
                r["url"] = decoder_redirection(r.get("url") or "")
            pertinents = resultats_pertinents(res, jetons or []) if res else []
            if journal is not None:
                journal.append(f"moteur {moteur} : {len(res)} résultat(s), {len(pertinents)} pertinent(s)")
            if pertinents:
                return pertinents
        except Exception as exc:  # noqa: BLE001
            log.info("recherche web %s en échec : %s", moteur, exc)
            if journal is not None:
                journal.append(f"moteur {moteur} : {type(exc).__name__}")
    return []


async def lire_page(url: str) -> tuple[str, list[str]]:
    """(texte visible, liens mailto) d'une page — direct, puis VPS si la
    page nous bloque ou n'a pas de contenu."""
    texte, mailtos = "", []
    try:
        statut, html = await _http_get(url)
        if statut < 400 and html:
            soup = _soup(html)
            for s in soup(["script", "style", "noscript"]):
                s.decompose()
            mailtos = [a.get("href", "") for a in soup.select('a[href^="mailto:"]')]
            texte = soup.get_text(" ", strip=True)
            # Un courriel coupé en deux balises (« rosibe</span>l@… ») est
            # perdu avec un séparateur : on ajoute le texte recollé par
            # bloc, qui ne sert qu'à l'extraction des courriels.
            try:
                colle = texte_colle_par_bloc(soup)
            except Exception:  # noqa: BLE001
                colle = ""
            if colle:
                texte = texte + " \n" + colle
    except Exception as exc:  # noqa: BLE001
        log.info("lecture directe %s en échec : %s", url, exc)
    if len(texte) < 200 and not mailtos:
        try:
            from app.integrations import scraping_proxy

            if scraping_proxy.vps_available():
                d = await scraping_proxy.scrape_page_text(url)
                if d:
                    texte = d.get("texte") or d.get("text") or texte
                    mailtos = list(d.get("mailtos") or []) or mailtos
        except Exception as exc:  # noqa: BLE001
            log.info("lecture VPS %s en échec : %s", url, exc)
    return texte, mailtos


# ─── Gemini avec recherche Google ────────────────────────────────────


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


async def _via_gemini(nom: str, agence: Optional[str], secteur: Optional[str]) -> Optional[dict]:
    """Demande à Gemini (outil google_search) le courriel professionnel.
    Renvoie {courriel, telephone, site_web, source_url, sources[]} ou None.
    Le résultat n'est JAMAIS cru sur parole : il est ensuite noté comme
    tout autre candidat (correspondance au nom, relecture de la page)."""
    api_key = (getattr(settings, "gemini_api_key", None) or "").strip()
    if not api_key:
        _DERNIER_GEMINI["raison"] = "clé GEMINI_API_KEY absente"
        return None
    from app.services.lead_extraction import (
        _GEMINI_BASE,
        _gemini_en_pause,
        _mettre_en_pause,
        resolve_gemini_cascade,
    )

    try:
        cascade = await resolve_gemini_cascade(api_key)
    except Exception:  # noqa: BLE001
        cascade = []
    modeles = [m for m in cascade if not _gemini_en_pause(m)][:2]
    if not modeles:
        _DERNIER_GEMINI["raison"] = "aucun modèle Gemini disponible (tous en pause)"
        return None
    _DERNIER_GEMINI["raison"] = None
    _DERNIER_GEMINI["essais"] = []
    prompt = (
        "Tu aides une entreprise immobilière du Québec à joindre un courtier immobilier. "
        f"Trouve l'adresse courriel PROFESSIONNELLE du courtier immobilier « {nom} »"
        + (f" de l'agence « {agence} »" if agence else "")
        + (f", qui travaille dans le secteur de {secteur}" if secteur else "")
        + ". Cherche sur le site de son agence (RE/MAX, Royal LePage, Sutton, Via Capitale, "
        "Proprio Direct, Century 21, EXP…), son site personnel ou les annuaires de courtiers. "
        "Réponds UNIQUEMENT par un objet JSON : "
        '{"courriel": "...", "telephone": "...", "site_web": "...", "source_url": "...", '
        '"certitude": "haute|moyenne|basse"}. Mets null quand tu ne trouves pas. '
        "N'invente JAMAIS un courriel : il doit apparaître tel quel sur une page que tu as lue."
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 512},
    }
    for modele in modeles:
        url = f"{_GEMINI_BASE}/models/{modele}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(url, params={"key": api_key}, json=payload)
            if resp.status_code == 429:
                _mettre_en_pause(modele, 600.0)
                _DERNIER_GEMINI["essais"].append(f"{modele}: HTTP 429 (quota)")
                continue
            if resp.status_code >= 400:
                log.warning(
                    "Gemini[%s] recherche courriel HTTP %s : %s",
                    modele, resp.status_code, (resp.text or "")[:300],
                )
                _DERNIER_GEMINI["essais"].append(
                    f"{modele}: HTTP {resp.status_code} {(resp.text or '')[:160]}"
                )
                if resp.status_code in (500, 502, 503, 504):
                    _mettre_en_pause(modele, 600.0)
                continue
            body = resp.json()
            cand = (body.get("candidates") or [{}])[0]
            parts = cand.get("content", {}).get("parts", []) or []
            texte = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))
            sources: list[str] = []
            for ch in (cand.get("groundingMetadata") or {}).get("groundingChunks") or []:
                uri = ((ch or {}).get("web") or {}).get("uri")
                if uri:
                    sources.append(uri)
            m = _JSON_RE.search(texte or "")
            data = json.loads(m.group(0)) if m else {}
            if not isinstance(data, dict):
                data = {}
            out = {
                "courriel": courriel_propre(data.get("courriel")),
                "telephone": data.get("telephone") or None,
                "site_web": data.get("site_web") or None,
                "source_url": data.get("source_url") or None,
                "certitude": data.get("certitude"),
                "sources": sources,
                "modele": modele,
            }
            _DERNIER_GEMINI["essais"].append(
                f"{modele}: réponse {len(texte or '')} car., {len(sources)} source(s), "
                f"courriel={out['courriel']}"
            )
            if out["courriel"] or out["site_web"] or sources:
                return out
            return None
        except Exception as exc:  # noqa: BLE001
            log.info("Gemini[%s] recherche courriel : %s", modele, exc)
            _DERNIER_GEMINI["essais"].append(f"{modele}: {type(exc).__name__}")
            continue
    return None


#: Dernier appel Gemini (diagnostic) : {raison, essais[]}.
_DERNIER_GEMINI: dict[str, Any] = {"raison": None, "essais": []}


# ─── Recherche d'un courtier ─────────────────────────────────────────


def _requetes(nom: str, agence: Optional[str], secteur: Optional[str]) -> list[str]:
    base = f'"{nom}" courtier immobilier'
    reqs = [base + (f" {agence}" if agence else "") + " courriel"]
    if agence:
        reqs.append(base + " courriel")
    if secteur and secteur.split("(")[0].strip():
        reqs.append(f'"{nom}" courtier {secteur.split("(")[0].strip()} courriel')
    return reqs[:2]


def _prioriser_pages(resultats: list[dict], nom: str, agence: Optional[str]) -> list[str]:
    """URLs à ouvrir : agence / nom dans le domaine ou le titre d'abord."""
    jet = set(t for t in tokens_nom(nom) if len(t) >= 3) | set(_jetons_agence(agence))
    notes: list[tuple[int, str]] = []
    vus: set[str] = set()
    for i, r in enumerate(resultats):
        url = r.get("url") or ""
        if not url or url in vus or _domaine_exclu(url):
            continue
        vus.add(url)
        bas = _sans_accents((url + " " + (r.get("titre") or "")).lower())
        n = sum(1 for t in jet if t in bas) * 10 - i
        if any(k in bas for k in ("remax", "royallepage", "sutton", "viacapitale", "propriodirect",
                                   "century21", "exprealty", "kw.com", "courtier", "agent")):
            n += 5
        notes.append((n, url))
    notes.sort(key=lambda x: -x[0])
    return [u for _, u in notes[:_MAX_PAGES_PAR_COURTIER]]


async def chercher_courriel(
    courtier: ProspectionCourtier, *, config: Optional[dict] = None,
    journal: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Cherche le courriel d'UN courtier. Renvoie
    {courriel, confiance, source, telephone, site_web, note, methode,
     ecartes: [...]} — courriel None si rien ne correspond au nom.
    ``journal`` (liste) reçoit une ligne par étape (diagnostic)."""
    def _j(msg: str) -> None:
        if journal is not None:
            journal.append(msg)

    nom = (courtier.nom or "").strip()
    agence = (courtier.agence or "").strip() or None
    secteur = (courtier.secteur or "").strip() or None
    moteurs = tuple(
        m.strip() for m in str((config or {}).get("recherche_moteurs") or "gemini,duckduckgo,bing").split(",") if m.strip()
    )
    candidats: dict[str, dict] = {}  # courriel → {score, raison, source, verifie}
    ecartes: list[str] = []
    telephone: Optional[str] = None
    site_web: Optional[str] = None
    methode: list[str] = []

    def _noter(courriel: Optional[str], source: str, texte_page: str = "") -> None:
        c = courriel_propre(courriel)
        if not c:
            return
        if _source_douteuse(source):
            _j(f"ignoré {c} ← {source[:90]} (site de recherche de personnes)")
            return
        score, raison = score_courriel(c, nom, agence)
        _j(f"candidat {c} ← {source[:90]} : {score} ({raison})")
        jet = tokens_nom(nom)
        nom_famille = jet[-1] if len(jet) > 1 else (jet[0] if jet else "")
        bas = _sans_accents(texte_page).lower() if texte_page else ""
        if score < 55 and bas and nom_famille and nom_famille in bas:
            # « rosibel@agence.com » sur la page qui porte « Rosibel
            # Martinez » : le prénom seul suffit quand le nom est là.
            local_a = re.sub(r"[^a-z]", "", _sans_accents(c.split("@")[0]).lower())
            prenom = jet[0] if jet else ""
            if len(prenom) >= 4 and local_a == prenom and "webmail" not in raison:
                score, raison = 60, "prénom seul, nom sur la page"
        if score < 55:
            if c not in ecartes:
                ecartes.append(c)
            return
        verifie = False
        if bas:
            verifie = c in bas and bool(nom_famille) and nom_famille in bas
        if verifie and any(d in (source or "").lower() for d in _DOMAINES_DONNEES_CONTACT):
            verifie = False  # annuaire de contacts : jamais « vérifié »
        prev = candidats.get(c)
        if prev is None or (score, verifie) > (prev["score"], prev["verifie"]):
            candidats[c] = {"score": score, "raison": raison, "source": source, "verifie": verifie}

    pages_lues: list[str] = []

    async def _lire_et_noter(url: str) -> None:
        if url in pages_lues or len(pages_lues) >= _MAX_PAGES_PAR_COURTIER or _domaine_exclu(url):
            return
        pages_lues.append(url)
        texte, mailtos = await lire_page(url)
        trouves = extraire_courriels(texte, mailtos)
        _j(f"page {url[:100]} : {len(texte)} car., {len(mailtos)} mailto, courriels {trouves[:5]}")
        for c in trouves:
            _noter(c, url, texte)

    async def _travail() -> None:
        nonlocal telephone, site_web
        # 1. Gemini + recherche Google : propose un courriel et des sources.
        if "gemini" in moteurs:
            g = await _via_gemini(nom, agence, secteur)
            _j(
                "gemini : " + (
                    f"{g.get('modele')} → courriel={g.get('courriel')} site={g.get('site_web')} "
                    f"source={g.get('source_url')} sources={len(g.get('sources') or [])}"
                    if g else f"rien ({_DERNIER_GEMINI.get('raison') or '; '.join(_DERNIER_GEMINI.get('essais') or []) or 'réponse vide'})"
                )
            )
            if g:
                methode.append(f"gemini:{g.get('modele')}")
                telephone = telephone or g.get("telephone")
                site_web = site_web or g.get("site_web")
                if g.get("courriel"):
                    _noter(g["courriel"], g.get("source_url") or "gemini")
                for u in ([g.get("source_url")] if g.get("source_url") else []) + list(g.get("sources") or [])[:3]:
                    if u and u.startswith("http"):
                        await _lire_et_noter(u)
                if g.get("site_web") and str(g["site_web"]).startswith("http"):
                    await _lire_et_noter(str(g["site_web"]))
            if any(v["verifie"] for v in candidats.values()):
                return
        # 2. Moteurs web : extraits puis pages.
        web_moteurs = tuple(m for m in moteurs if m in MOTEURS_WEB_DEFAUT) or MOTEURS_WEB_DEFAUT
        for requete in _requetes(nom, agence, secteur):
            resultats = await rechercher_web(
                requete, moteurs=web_moteurs, jetons=tokens_nom(nom), journal=journal
            )
            _j(f"web « {requete} » : {len(resultats)} résultat(s) — " + "; ".join(
                (r.get("url") or "")[:80] for r in resultats[:6]
            ))
            if resultats:
                methode.append("web")
            for r in resultats:
                for c in extraire_courriels(r.get("extrait") or ""):
                    _noter(c, r.get("url") or "extrait")
            for url in _prioriser_pages(resultats, nom, agence):
                await _lire_et_noter(url)
                if any(v["verifie"] for v in candidats.values()):
                    return
            if candidats:
                return

    try:
        await asyncio.wait_for(_travail(), timeout=_BUDGET_PAR_COURTIER_S)
    except asyncio.TimeoutError:
        methode.append("budget dépassé")
    except Exception as exc:  # noqa: BLE001
        log.warning("recherche courriel %s : %s", nom, exc, exc_info=True)
        methode.append(f"erreur {type(exc).__name__}")

    meilleur: Optional[tuple[str, dict]] = None
    for c, v in candidats.items():
        if meilleur is None or (v["verifie"], v["score"]) > (meilleur[1]["verifie"], meilleur[1]["score"]):
            meilleur = (c, v)
    if meilleur:
        c, v = meilleur
        return {
            "courriel": c,
            "confiance": "verifie" if v["verifie"] else "probable",
            "source": v["source"],
            "telephone": telephone,
            "site_web": site_web,
            "note": (
                f"{v['raison']} — {len(pages_lues)} page(s) lue(s)"
                + (f" ; écartés : {', '.join(ecartes[:4])}" if ecartes else "")
                + (f" ; via {','.join(methode)}" if methode else "")
            ),
            "methode": ",".join(methode) or "aucune",
            "ecartes": ecartes,
        }
    return {
        "courriel": None,
        "confiance": None,
        "source": None,
        "telephone": telephone,
        "site_web": site_web,
        "note": (
            f"aucun courriel au nom du courtier — {len(pages_lues)} page(s) lue(s)"
            + (f" ; écartés : {', '.join(ecartes[:4])}" if ecartes else "")
            + (f" ; via {','.join(methode)}" if methode else "")
        ),
        "methode": ",".join(methode) or "aucune",
        "ecartes": ecartes,
    }


# ─── Enrichissement en lot ───────────────────────────────────────────


async def enrichir_courriels(
    db: AsyncSession,
    *,
    config: dict[str, Any],
    courtier_ids: Optional[list[int]] = None,
    max_courtiers: int = 20,
    forcer: bool = False,
    progres: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Cherche le courriel des courtiers qui n'en ont pas (ou des ids
    donnés). Un courtier déjà cherché il y a moins de
    ``recherche_courriel_ttl_jours`` n'est pas recherché de nouveau (sauf
    ``forcer``). Enregistre fiche par fiche (commit) : rien n'est perdu si
    le serveur redémarre. Renvoie un rapport chiffré."""
    ttl = int(config.get("recherche_courriel_ttl_jours") or 30)
    limite = datetime.now(timezone.utc) - timedelta(days=ttl)
    stmt = select(ProspectionCourtier)
    if courtier_ids:
        stmt = stmt.where(ProspectionCourtier.id.in_(list(courtier_ids)))
    else:
        stmt = stmt.where(
            (ProspectionCourtier.courriel.is_(None)) | (ProspectionCourtier.courriel == ""),
            ProspectionCourtier.statut != "ignorer",
        )
    stmt = stmt.order_by(ProspectionCourtier.dernier_vu_le.desc().nullslast(), ProspectionCourtier.id.asc())
    rows = (await db.execute(stmt)).scalars().all()
    rapport: dict[str, Any] = {
        "examines": 0, "trouves": 0, "verifies": 0, "probables": 0,
        "sans_resultat": 0, "sautes_recemment_cherches": 0, "erreurs": [], "details": [],
    }
    for c in rows:
        if rapport["examines"] >= max(0, int(max_courtiers)):
            break
        if not forcer and not courtier_ids and c.courriel_cherche_le is not None:
            cherche = c.courriel_cherche_le
            if cherche.tzinfo is None:
                cherche = cherche.replace(tzinfo=timezone.utc)
            if cherche > limite:
                rapport["sautes_recemment_cherches"] += 1
                continue
        if rapport["examines"] > 0:
            # Politesse envers les moteurs : 2 à 5 s entre deux courtiers.
            await asyncio.sleep(random.uniform(2.0, 5.0))
        rapport["examines"] += 1
        if progres:
            try:
                progres(f"Courriels manquants : {rapport['examines']}/{max_courtiers} — {c.nom}")
            except Exception:  # noqa: BLE001
                pass
        try:
            res = await chercher_courriel(c, config=config)
            c.courriel_cherche_le = datetime.now(timezone.utc)
            c.courriel_recherche_note = (res.get("note") or "")[:500] or None
            if res.get("courriel") and not c.courriel:
                c.courriel = res["courriel"]
                c.courriel_source = (str(res.get("source") or ""))[:500] or None
                c.courriel_confiance = res.get("confiance")
                rapport["trouves"] += 1
                rapport["verifies" if res.get("confiance") == "verifie" else "probables"] += 1
            elif res.get("courriel") and c.courriel:
                # Déjà un courriel (ids forcés) : on garde le sien, on note.
                c.courriel_recherche_note = (f"trouvé aussi : {res['courriel']} — " + (res.get("note") or ""))[:500]
            else:
                rapport["sans_resultat"] += 1
            if res.get("telephone") and not c.telephone:
                from app.services.prospection_courtiers import _telephone_propre

                c.telephone = _telephone_propre(str(res["telephone"]))
            if res.get("site_web") and not c.site_web and str(res["site_web"]).startswith("http"):
                c.site_web = str(res["site_web"])[:500]
            if len(rapport["details"]) < 50:
                rapport["details"].append({
                    "id": c.id, "nom": c.nom, "courriel": res.get("courriel"),
                    "confiance": res.get("confiance"), "source": res.get("source"),
                    "methode": res.get("methode"),
                })
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("enrichissement courriel %s en échec", c.id, exc_info=True)
            await db.rollback()
            rapport["erreurs"].append(f"{c.nom} : {type(exc).__name__}: {str(exc)[:120]}")
    return rapport


__all__ = [
    "tokens_nom",
    "courriel_propre",
    "score_courriel",
    "extraire_courriels",
    "deobfusquer",
    "decoder_redirection_bing",
    "decoder_redirection",
    "texte_colle_par_bloc",
    "parser_duckduckgo",
    "parser_bing",
    "rechercher_web",
    "resultats_pertinents",
    "MOTEURS_WEB_DEFAUT",
    "lire_page",
    "chercher_courriel",
    "enrichir_courriels",
]
