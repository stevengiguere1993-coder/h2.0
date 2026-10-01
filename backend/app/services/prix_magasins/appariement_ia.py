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


async def choisir_parmi(nom: str, candidats: list[Candidat]) -> tuple[Optional[Candidat], float, str]:
    """Demande à l'IA lequel des candidats est LE même article que le
    matériau. Renvoie (candidat ou None, confiance, raison)."""
    cands = [c for c in candidats if (c.title or "").strip()][:MAX_CANDIDATS]
    if not cands or not disponible():
        return None, 0.0, ""
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
        "Un format d'emballage différent (unité vs paquet) est acceptable si l'article est le même.\n"
        'Format : {"index": <numéro ou null>, "confiance": <0 à 1>, "raison": "<10 mots max>"}'
    )
    data = _json(await _appel(prompt, max_tokens=120))
    if not isinstance(data, dict):
        return None, 0.0, ""
    idx = data.get("index")
    try:
        conf = max(0.0, min(1.0, float(data.get("confiance") or 0.0)))
    except (TypeError, ValueError):
        conf = 0.0
    raison = str(data.get("raison") or "")[:120]
    if idx is None or not isinstance(idx, (int, float)) or not (1 <= int(idx) <= len(cands)):
        return None, conf, raison
    if conf < SEUIL_CONFIANCE:
        return None, conf, raison
    return cands[int(idx) - 1], conf, raison
