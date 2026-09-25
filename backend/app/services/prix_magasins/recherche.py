"""Recherche d'un produit sur le site d'un détaillant (étape 3 bis du
catalogue, 2026-09-26) : « un prix de base pour chaque matériau, pas une
case vide ».

Chaque module de magasin peut exposer ::

    async def search(query: str) -> list[Candidat]

qui interroge le moteur de recherche du site (API JSON quand elle existe,
page de résultats rendue par le VPS sinon) et renvoie des candidats
(URL produit, titre, n° d'article, prix si la recherche le donne).

Ce module fournit le NOTATEUR commun : ``choisir(nom_materiau, candidats)``
retient le candidat dont le titre couvre le mieux les mots et surtout les
NOMBRES du matériau (dimensions, formats : « 1/2 po », « 4 x 8 », « 3,78
L »). Les fractions et virgules sont normalisées (1/2 → 0.5, 3,78 → 3.78,
1-1/4 → 1.25) pour comparer « 0.5 po » et « 1/2 po ». Sans correspondance
suffisante, on ne devine pas : pas de prix plutôt qu'un mauvais prix.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


@dataclass
class Candidat:
    url: str
    title: str
    sku: Optional[str] = None
    price: Optional[float] = None
    regular_price: Optional[float] = None
    on_sale: bool = False
    in_stock: Optional[bool] = None
    extra: dict[str, Any] = field(default_factory=dict)
    #: Rempli par ``choisir``.
    score: float = 0.0


#: Mots vides ou trop génériques pour compter dans le score.
_STOP = {
    "de", "du", "des", "la", "le", "les", "et", "en", "a", "au", "aux", "pour",
    "avec", "sans", "par", "sur", "un", "une", "d", "l", "the", "of", "for",
    "x", "po", "pi", "pi2", "pc", "pcs", "ea", "ch", "un", "unite", "boite",
    "bte", "pqt", "paquet", "sac", "gal", "l", "ml", "kg", "g", "lb", "in",
    "ft", "mm", "cm", "m", "type", "regulier", "standard",
}

#: Synonymes → forme canonique (après retrait des accents).
_SYNONYMES = {
    "gyproc": "gypse", "drywall": "gypse", "placoplatre": "gypse",
    "plywood": "contreplaque", "osb": "osb",
    "epinette": "epinette", "spruce": "epinette", "spf": "epinette",
    "2x4": "2 x 4", "2x6": "2 x 6", "2x3": "2 x 3", "2x8": "2 x 8", "2x10": "2 x 10",
    "4x8": "4 x 8", "1x4": "1 x 4", "1x6": "1 x 6", "1x3": "1 x 3",
    "pouce": "po", "pouces": "po", "pied": "pi", "pieds": "pi", "inch": "po",
    "litre": "l", "litres": "l", "liter": "l",
    "screw": "vis", "screws": "vis", "nail": "clou", "nails": "clou", "clous": "clou",
    "vis": "vis", "paint": "peinture", "primer": "appret",
}

_FRACTION_RE = re.compile(r"(?<![\d.])(\d+)(?:[ -](\d+)/(\d+)|/(\d+))(?![\d.])")
_DEC_COMMA_RE = re.compile(r"(\d),(\d)")
_DIM_RE = re.compile(r"(\d)\s*[x×]\s*(\d)")


def _sans_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _fraction(m: re.Match) -> str:
    a = int(m.group(1))
    if m.group(2) and m.group(3):
        try:
            return _fmt(a + int(m.group(2)) / int(m.group(3)))
        except ZeroDivisionError:
            return m.group(0)
    if m.group(4):
        try:
            return _fmt(a / int(m.group(4)))
        except ZeroDivisionError:
            return m.group(0)
    return m.group(0)


def _fmt(x: float) -> str:
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return s or "0"


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, fractions et virgules décimales
    normalisées, « 4x8 » → « 4 x 8 », synonymes appliqués."""
    s = _sans_accents((texte or "").lower())
    s = s.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    s = s.replace("''", " po ").replace('"', " po ").replace("’", "'")
    s = _DEC_COMMA_RE.sub(r"\1.\2", s)
    s = _FRACTION_RE.sub(_fraction, s)
    s = _DIM_RE.sub(r"\1 x \2", s)
    s = re.sub(r"[^a-z0-9. ]+", " ", s)
    mots = []
    for w in s.split():
        w = w.strip(".")
        if not w:
            continue
        w = _SYNONYMES.get(w, w)
        mots.extend(w.split())
    return " ".join(mots)


def _marques(texte: str) -> set[str]:
    """Mots écrits en MAJUSCULES ou Capitalisés hors début de phrase
    (« CGC », « Glidden », « Sheetrock ») : des marques / gammes, qui
    pèsent double — un autre fabricant, c'est un autre produit."""
    out: set[str] = set()
    for i, w in enumerate((texte or "").replace("\u00a0", " ").split()):
        w2 = re.sub(r"[^A-Za-zÀ-ÿ0-9]", "", w)
        if len(w2) < 3 or not w2[0].isalpha():
            continue
        if w2.isupper() or (i > 0 and w2[0].isupper() and w2[1:].islower()):
            out.add(normaliser(w2))
    return out


def _tokens(texte: str) -> tuple[set[str], set[str]]:
    """(nombres, mots) significatifs du texte normalisé. Les nombres
    sont ramenés à une forme canonique (« 4.0 » → « 4 »)."""
    nombres: set[str] = set()
    mots: set[str] = set()
    for w in normaliser(texte).split():
        if re.fullmatch(r"\d+(?:\.\d+)?", w):
            try:
                nombres.add(_fmt(float(w)))
            except ValueError:
                nombres.add(w)
        elif len(w) >= 3 and w not in _STOP:
            mots.add(w)
    return nombres, mots


def _racine(w: str) -> str:
    """Racine grossière (pluriels, féminins) pour comparer « panneaux »
    et « panneau », « isolante » et « isolant »."""
    for suf in ("aux", "eaux", "es", "s", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def score(nom_materiau: str, titre: str) -> float:
    """Part (0-1) des nombres (poids 2) et mots (poids 1) du matériau
    retrouvés dans le titre. 0 dès qu'un nombre du matériau manque : une
    dimension absente, c'est un autre produit."""
    n_m, w_m = _tokens(nom_materiau)
    n_t, w_t = _tokens(titre)
    if not n_m and not w_m:
        return 0.0
    if n_m and not n_m.issubset(n_t):
        return 0.0
    racines_t = {_racine(w) for w in w_t}
    marques = _marques(nom_materiau)
    poids = {w: (2.0 if w in marques else 1.0) for w in w_m}
    total = 2.0 * len(n_m) + sum(poids.values())
    got = 2.0 * len(n_m) + sum(
        poids[w] for w in w_m if w in w_t or _racine(w) in racines_t
    )
    return round(got / total, 3) if total else 0.0


#: Score minimal pour accepter un candidat (au-dessus du « 3 sur 5 » qui
#: laissait passer une peinture extérieure pour une peinture de plafond).
SEUIL = 0.7


def choisir(nom_materiau: str, candidats: Iterable[Candidat], seuil: float = SEUIL) -> Optional[Candidat]:
    """Meilleur candidat (score ≥ seuil) ; à score égal, l'ordre de la
    recherche (pertinence du site) prime. Les candidats sont annotés."""
    best: Optional[Candidat] = None
    for c in candidats:
        c.score = score(nom_materiau, c.title or "")
        if c.score >= seuil and (best is None or c.score > best.score):
            best = c
    return best


def variantes(nom: str) -> list[str]:
    """Requêtes à essayer dans l'ordre : le nom tel quel, sa forme
    normalisée (fractions → décimales, « 4x8 » → « 4 x 8 »), puis les
    seuls mots et nombres significatifs (les moteurs qui exigent tous
    les termes n'aiment pas « 3,78 L » ou « 2x4x8 »)."""
    out: list[str] = []
    n_m, w_m = _tokens(nom)
    for q in (nom.strip(), normaliser(nom), " ".join(sorted(w_m) + sorted(n_m))):
        q = re.sub(r"\s+", " ", q).strip()
        if q and q.lower() not in {x.lower() for x in out}:
            out.append(q)
    return out


def money_any(v: Any) -> Optional[float]:
    from . import parse_money

    return parse_money(v)
