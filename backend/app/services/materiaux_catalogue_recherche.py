"""Recherche TOLÉRANTE dans le catalogue de matériaux (retour Phil
2026-10-02) : les noms viennent des factures (« adapt 3/4 ff 3/4 »,
« Epinette 2x4x8 », « epin. 2x6 ») et la même chose s'écrit de dix
façons. On compare des JETONS normalisés (minuscules, sans accents,
abréviations développées, « 2x4x8 » → « 2 x 4 x 8 », fractions → décimales
— même moteur que l'appariement avec les sites) :

- « 2x4x6 » trouve « Épinette 2 x 4 x 6 », « 2x4x6' EPS », pas « 2x4x8 » ;
- « epinette » trouve « Épinette… », « epin 2x6 », « EPS 2x4 » ;
- « adapt 3/4 » trouve « Adaptateur 3/4 po FIP », « adapt. 3/4 ff 3/4 ».

Tous les jetons de la requête doivent se retrouver (égalité, ou préfixe
pour un mot d'au moins 3 lettres). Classement : nom qui commence par la
requête d'abord, puis moins de jetons en trop, puis alphabétique.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from app.services.prix_magasins.recherche import normaliser

_IGNORE = {"x", "po", "pi", "de", "du", "la", "le", "et", "en", "a", "un", "une", "des"}


def jetons(texte: str) -> list[str]:
    out: list[str] = []
    for w in normaliser(texte or "").split():
        w = w.strip("./")
        if w and w not in _IGNORE:
            out.append(w)
    return out


def _nombre(w: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?(?:/\d+)?", w))


def _match(q: str, mots: list[str]) -> bool:
    if q in mots:
        return True
    if _nombre(q):
        return False  # un nombre ne se « préfixe » pas (2 ≠ 24)
    if len(q) >= 3:
        return any(m.startswith(q) for m in mots if not _nombre(m))
    return False


def score(query_tokens: list[str], nom: str) -> float:
    """0 = pas trouvé ; sinon plus grand = meilleur."""
    mots = jetons(nom)
    if not query_tokens or not mots:
        return 0.0
    if any(not _match(q, mots) for q in query_tokens):
        return 0.0
    s = 1.0
    if mots[0] == query_tokens[0] or mots[0].startswith(query_tokens[0]) and not _nombre(query_tokens[0]):
        s += 0.5
    exacts = sum(1 for q in query_tokens if q in mots)
    s += 0.1 * exacts
    s -= 0.02 * max(0, len(mots) - len(query_tokens))
    return round(s, 4)


def classer(materiaux: Iterable, q: str, limit: Optional[int] = None) -> list:
    """Matériaux (objets avec ``.name``) qui répondent à ``q``, du
    meilleur au moins bon. Repli : sous-chaîne brute du nom (cas d'un
    jeton de 1-2 lettres, « ss », « pvc ») ."""
    qt = jetons(q)
    brut = (q or "").strip().lower()
    scored: list[tuple[float, str, object]] = []
    for m in materiaux:
        s = score(qt, m.name) if qt else 0.0
        if s <= 0 and brut and brut in (m.name or "").lower():
            s = 0.5
        if s > 0:
            scored.append((s, (m.name or "").lower(), m))
    scored.sort(key=lambda t: (-t[0], t[1]))
    out = [m for _, _, m in scored]
    return out[:limit] if limit else out


def cle_doublon(nom: str) -> str:
    """Clé de regroupement des DOUBLONS : jetons normalisés triés (« adapt
    3/4 ff 3/4 » = « Adaptateur 3/4 FF 3/4 » = « adapt. 3/4 ff3/4 »)."""
    return " ".join(sorted(jetons(nom)))
