"""Appariement par IA (Gemini via la chaîne de providers ``app.integrations.ai``)
entre le NOM d'un matériau du catalogue et les PRODUITS du site d'un
magasin — retour Phil 2026-10-01 : « il faudrait que Gemini fasse le lien
entre les items écrits et les correspondances sur les sites ».

Deux usages, tous deux facultatifs (sans clé IA, la recherche garde le
seul notateur par règles de ``recherche.py``) :

1. ``requetes_pour(nom)`` : réécrit un nom de catalogue abrégé
   (« adapt 3/4 ff 3/4 ») en requêtes telles qu'on les tape sur le site
   d'une quincaillerie (« adaptateur 3/4 po femelle femelle »).
2. ``choisir_parmi(nom, candidats)`` : quand aucun candidat ne passe le
   notateur par règles, demande à l'IA lequel est LE même article
   (type, dimension, matière, format) — ou aucun. Seuil de confiance,
   et un article apparié par IA est noté comme tel sur l'offre pour
   contrôle visuel.

Garde-fous : 2 appels IA en parallèle au plus, cache des requêtes par
nom, disjoncteur (3 échecs consécutifs → pause de 10 min) pour qu'une
clé en quota ne ralentisse pas toute la course.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional

from .recherche import Candidat, normaliser

log = logging.getLogger(__name__)

SEUIL_CONFIANCE = 0.7
MAX_CANDIDATS = 15
_PAUSE_PANNE_S = 600.0

_sem = asyncio.Semaphore(2)
_cache_requetes: dict[str, list[str]] = {}
_echecs = 0
_panne_jusqua = 0.0

_SYSTEM = (
    "Tu es acheteur de matériaux pour un entrepreneur en construction au Québec. "
    "Tu connais le vocabulaire des quincailleries (Home Depot, Rona, BMR, Canac, "
    "Patrick Morin) et les abréviations de chantier : adapt = adaptateur, "
    "ff = femelle-femelle, fm = femelle-mâle, mm = mâle-mâle, po ou \" = pouce, "
    "pi ou ' = pied, cu = cuivre, galv = galvanisé, pex, abs, pvc, gyproc = gypse. "
    "Tu réponds UNIQUEMENT en JSON valide, sans texte autour, sans balises markdown."
)


def disponible() -> bool:
    """Une clé IA est configurée et le disjoncteur n'est pas ouvert."""
    try:
        from app.integrations.ai import is_configured
    except Exception:  # noqa: BLE001
        return False
    return bool(is_configured()) and time.monotonic() >= _panne_jusqua


def _noter_echec(exc: Exception) -> None:
    global _echecs, _panne_jusqua
    _echecs += 1
    log.warning("Appariement IA : échec %s (%s)", _echecs, str(exc)[:200])
    if _echecs >= 3:
        _panne_jusqua = time.monotonic() + _PAUSE_PANNE_S
        _echecs = 0
        log.warning("Appariement IA : disjoncteur ouvert pour %.0f s", _PAUSE_PANNE_S)


async def _appel(prompt: str, *, max_tokens: int = 400) -> Optional[str]:
    global _echecs
    if not disponible():
        return None
    from app.integrations.ai import complete

    async with _sem:
        try:
            res = await complete(
                prompt=prompt, system=_SYSTEM, max_tokens=max_tokens, temperature=0.0, thinking_budget=0,
            )
        except Exception as exc:  # noqa: BLE001
            _noter_echec(exc)
            return None
    _echecs = 0
    return res.text


def _json(text: Optional[str]) -> Any:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        return json.loads(t)
    except ValueError:
        m = re.search(r"[\[{].*[\]}]", t, flags=re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except ValueError:
            return None


async def requetes_pour(nom: str) -> list[str]:
    """2 à 3 requêtes de recherche « site de quincaillerie » pour un nom
    de catalogue, de la plus précise à la plus générale. Vide sans IA."""
    cle = normaliser(nom)
    if cle in _cache_requetes:
        return list(_cache_requetes[cle])
    if not disponible():
        return []
    prompt = (
        "Nom d'un matériau tel qu'écrit dans le catalogue interne (abréviations, "
        f"fautes possibles) : « {nom.strip()} ».\n"
        "Donne 3 requêtes de recherche courtes (2 à 6 mots, en français, sans ponctuation "
        "superflue) telles qu'on les taperait sur le site d'une quincaillerie pour trouver "
        "EXACTEMENT cet article, de la plus précise à la plus générale. Développe les "
        "abréviations, garde les dimensions et formats tels quels (3/4, 1/2 po, 4 x 8, 3,78 L).\n"
        'Format : {"requetes": ["...", "...", "..."]}'
    )
    data = _json(await _appel(prompt, max_tokens=200))
    out: list[str] = []
    if isinstance(data, dict):
        for q in data.get("requetes") or []:
            if isinstance(q, str):
                q = re.sub(r"\s+", " ", q).strip()[:80]
                if q and q.lower() not in {x.lower() for x in out}:
                    out.append(q)
    out = out[:3]
    if len(_cache_requetes) > 2000:
        _cache_requetes.clear()
    _cache_requetes[cle] = list(out)
    return out


async def choisir_parmi(nom: str, candidats: list[Candidat]) -> tuple[Optional[Candidat], float, str, bool]:
    """Demande à l'IA lequel des candidats est LE même article que le
    matériau. Renvoie (candidat ou None, confiance, raison, repondu) —
    ``repondu`` False = pas de réponse exploitable (IA absente, quota,
    JSON illisible), à distinguer d'un « aucun » explicite."""
    cands = [c for c in candidats if (c.title or "").strip()][:MAX_CANDIDATS]
    if not cands or not disponible():
        return None, 0.0, "", False
    lignes = []
    for i, c in enumerate(cands, start=1):
        prix = f" — {c.price:.2f} $" if (c.price is not None and c.price > 0) else ""
        lignes.append(f"{i}. {c.title.strip()[:140]}{prix}")
    prompt = (
        f"Matériau du catalogue : « {nom.strip()} ».\n"
        "Produits renvoyés par la recherche du site du magasin :\n" + "\n".join(lignes) + "\n\n"
        "Lequel est LE MÊME article (même type de produit, mêmes dimensions / format / "
        "diamètre, même matière, même finition) ? Un produit d'une autre dimension, d'un "
        "autre diamètre ou d'un autre type n'est PAS le même article : réponds alors null. "
        "Un format d'emballage différent (unité vs paquet) est acceptable si l'article est le même. "
        "Une caractéristique que le nom du catalogue ne précise pas (longueur d'une pièce de bois, "
        "couleur, marque, classe) n'est PAS un critère d'exclusion : prends alors le candidat le plus "
        "courant. Le catalogue vient de factures de fournisseurs : abréviations et fautes sont normales.\n"
        'Format : {"index": <numéro ou null>, "confiance": <0 à 1>, "raison": "<10 mots max>"}'
    )
    data = _json(await _appel(prompt, max_tokens=120))
    if not isinstance(data, dict):
        return None, 0.0, "", False
    idx = data.get("index")
    try:
        conf = max(0.0, min(1.0, float(data.get("confiance") or 0.0)))
    except (TypeError, ValueError):
        conf = 0.0
    raison = str(data.get("raison") or "")[:120]
    if idx is None or not isinstance(idx, (int, float)) or not (1 <= int(idx) <= len(cands)):
        return None, conf, raison, True
    if conf < SEUIL_CONFIANCE:
        return None, conf, raison, True
    return cands[int(idx) - 1], conf, raison, True


# ───────────── Recherche WEB par l'IA (Gemini + Google Search) ─────────────
#
# Quand le site du magasin bloque nos recherches (Rona / BMR derrière
# Cloudflare, même depuis le VPS) ou ne renvoie rien d'approchant, on
# demande à Gemini, outillé de la recherche Google, de trouver LA page
# produit du site qui correspond au matériau et son prix affiché. Les
# sources citées (groundingChunks) sont des redirections Google : on les
# résout (en-tête Location, sans charger la page) pour obtenir l'URL
# réelle et n'accepter qu'une page DU site du magasin.

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
MODELE_WEB = "gemini-2.5-flash"
SEUIL_WEB = 0.6


def _cle_gemini() -> str:
    import os

    try:
        from app.core.config import settings

        k = (getattr(settings, "gemini_api_key", None) or "").strip()
    except Exception:  # noqa: BLE001
        k = ""
    return k or (os.getenv("GEMINI_API_KEY") or "").strip()


def web_disponible() -> bool:
    return bool(_cle_gemini()) and time.monotonic() >= _panne_jusqua


def _domaine(url: str) -> str:
    from urllib.parse import urlparse

    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _meme_domaine(url: str, domaine: str) -> bool:
    d = _domaine(url)
    return bool(d) and bool(domaine) and (d == domaine or d.endswith("." + domaine))


async def _resoudre_redirect(uri: str) -> Optional[str]:
    """URL réelle derrière une redirection Google (sans charger la cible)."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=5.0), follow_redirects=False) as c:
            r = await c.get(uri)
        if 300 <= r.status_code < 400:
            return r.headers.get("location")
        return str(r.url) if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


async def rechercher_web(nom: str, site: str, magasin_name: str) -> Optional[Candidat]:
    """Trouve, via Gemini + Google Search, la page produit de ``site`` qui
    correspond au matériau ``nom``, avec le prix lu dans les résultats.
    None si rien de sûr. Ne lève jamais."""
    import httpx

    key = _cle_gemini()
    domaine = _domaine(site if "://" in (site or "") else f"https://{site}")
    if not key or not domaine or not web_disponible():
        return None
    prompt = (
        f"Matériau du catalogue d'un entrepreneur (abréviations de facture possibles) : « {nom.strip()} ».\n"
        f"Cherche avec Google, en te limitant au site {domaine} (requêtes « site:{domaine} … »), LA page produit "
        f"de {magasin_name} qui est LE MÊME article (même type, mêmes dimensions / diamètre / format, même matière). "
        "Lis le prix affiché dans les résultats (prix régulier et prix en rabais s'il y a lieu, en $ CAD).\n"
        "Réponds UNIQUEMENT ce JSON : "
        '{"url": "<URL complète de la page produit sur le site, ou null>", "title": "<titre du produit>", '
        '"price": <prix courant ou null>, "regular_price": <prix régulier si en rabais, sinon null>, '
        '"on_sale": <true|false>, "confiance": <0 à 1>, "raison": "<10 mots max>"}\n'
        "Si aucun produit du site ne correspond vraiment, url = null et confiance = 0. Ne devine jamais un prix."
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": _SYSTEM}]},
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 700},
    }
    url = f"{GEMINI_BASE}/models/{MODELE_WEB}:generateContent?key={key}"
    async with _sem:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as c:
                r = await c.post(url, json=payload)
            if r.status_code != 200:
                _noter_echec(RuntimeError(f"Gemini web HTTP {r.status_code}: {r.text[:160]}"))
                return None
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            _noter_echec(exc)
            return None
    global _echecs
    _echecs = 0
    try:
        cand0 = (data.get("candidates") or [{}])[0]
        parts = (cand0.get("content") or {}).get("parts") or []
        texte = "\n".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))
        chunks = ((cand0.get("groundingMetadata") or {}).get("groundingChunks") or [])
    except Exception:  # noqa: BLE001
        return None
    d = _json(texte)
    if not isinstance(d, dict):
        return None
    try:
        conf = max(0.0, min(1.0, float(d.get("confiance") or 0.0)))
    except (TypeError, ValueError):
        conf = 0.0
    if conf < SEUIL_WEB:
        return None
    # URL : celle du modèle si elle est bien sur le site, sinon la première
    # source citée (résolue) qui est sur le site.
    url_prod = str(d.get("url") or "").strip()
    if not _meme_domaine(url_prod, domaine):
        url_prod = ""
        for ch in chunks[:8]:
            uri = str(((ch or {}).get("web") or {}).get("uri") or "")
            if not uri:
                continue
            reel = uri if _meme_domaine(uri, domaine) else await _resoudre_redirect(uri)
            if reel and _meme_domaine(reel, domaine):
                url_prod = reel
                break
    if not url_prod:
        return None

    def _num(v: Any) -> Optional[float]:
        try:
            x = float(v)
            return round(x, 2) if x > 0 else None
        except (TypeError, ValueError):
            return None

    price, regular = _num(d.get("price")), _num(d.get("regular_price"))
    on_sale = bool(d.get("on_sale")) and regular is not None and price is not None and regular > price
    return Candidat(
        url=url_prod[:500], title=str(d.get("title") or nom)[:255], sku=None,
        price=price, regular_price=(regular if on_sale else None), on_sale=on_sale,
        extra={"ia_web": True, "raison": str(d.get("raison") or "")[:120]}, score=conf,
    )
