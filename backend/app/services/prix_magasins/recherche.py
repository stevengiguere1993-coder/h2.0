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
    "epinette": "epinette", "spruce": "epinette", "spf": "epinette", "eps": "epinette",
    "2x4": "2 x 4", "2x6": "2 x 6", "2x3": "2 x 3", "2x8": "2 x 8", "2x10": "2 x 10",
    "4x8": "4 x 8", "1x4": "1 x 4", "1x6": "1 x 6", "1x3": "1 x 3",
    "pouce": "po", "pouces": "po", "pied": "pi", "pieds": "pi", "inch": "po",
    "litre": "l", "litres": "l", "liter": "l",
    "screw": "vis", "screws": "vis", "nail": "clou", "nails": "clou", "clous": "clou",
    "vis": "vis", "paint": "peinture", "primer": "appret",
    # Abréviations de FACTURE (le catalogue vient des factures de fournisseurs,
    # retour Phil 2026-10-01) et vocabulaire des sites (FIP / MIP) : les deux
    # côtés passent par ``normaliser``, donc « ff » ↔ « FIP x FIP ».
    "adapt": "adaptateur", "adapt.": "adaptateur", "adaptor": "adaptateur", "adapter": "adaptateur",
    "ff": "femelle femelle", "fm": "femelle male", "mf": "male femelle",
    "fip": "femelle", "fpt": "femelle", "mip": "male", "mpt": "male", "fem": "femelle",
    "femelle": "femelle", "male": "male", "mal": "male",
    "cu": "cuivre", "cuiv": "cuivre", "galv": "galvanise", "galvanize": "galvanise", "galvanized": "galvanise",
    "gyp": "gypse", "ctp": "contreplaque", "epin": "epinette",
    "elec": "electrique", "elect": "electrique", "ext": "exterieur", "int": "interieur",
    "alim": "alimentation", "amenee": "alimentation", "tuy": "tuyau", "rac": "raccord", "racc": "raccord",
    "coud": "coude", "cde": "coude", "rob": "robinet", "siph": "siphon", "fem.": "femelle",
    "piv": "pivotant", "ss": "inoxydable", "inox": "inoxydable", "stainless": "inoxydable",
    "tte": "toilette", "toil": "toilette", "lav": "lavabo", "evier": "evier",
    "bte": "boite", "sch": "cedule", "sch40": "cedule 40", "sch80": "cedule 80",
}

#: Expressions composées → jeton unique (après retrait des accents).
_EXPRESSIONS = (
    ("cloison seche", "gypse"), ("cloisons seches", "gypse"), ("panneau de platre", "gypse"),
    ("type x", "typex"), ("type c", "typec"), ("mold tough", "moldtough"),
    ("resistant a l'eau", "hydrofuge"), ("resistant a l eau", "hydrofuge"),
    ("resistant au feu", "coupefeu"), ("coupe-feu", "coupefeu"), ("coupe feu", "coupefeu"),
    ("bois traite", "traite"), ("pression traite", "traite"),
)

#: Fractions de pouce seulement (dénominateur 2, 4, 8, 16, 32, 64 et
#: numérateur plus petit) : « 1/2 », « 1 1/4 », « 1-5/8 ». « 14/2 » (calibre
#: de fil), « 12/3 », « 90 14/2 » restent tels quels.
_FRACTION_RE = re.compile(
    r"(?:(?<=^)|(?<=[ (]))(\d+)(?:[ -](\d+)/(\d+)|/(\d+))(?![\d./])"
)
_DENOMS = {2, 4, 8, 16, 32, 64}
_DEC_COMMA_RE = re.compile(r"(\d),(\d)")
#: « 2x4x8 », « 2 x 4 x 6 » → « 2 x 4 x 8 » (lookarounds : la chaîne
#: 2x4x6 doit donner trois nombres, pas « 2 » et « 4x6 »).
_DIM_RE = re.compile(r"(?<=\d)\s*[x×]\s*(?=\d)")
#: « ff3/4 », « cu1/2 » : lettres collées à une fraction → séparées.
_LETTRE_FRACTION_RE = re.compile(r"(?<=[a-z])(?=\d+/\d+)")


def _sans_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _fraction(m: re.Match) -> str:
    a = int(m.group(1))
    if m.group(2) and m.group(3):
        n, d = int(m.group(2)), int(m.group(3))
        if d in _DENOMS and 0 < n < d:
            return _fmt(a + n / d)
        return m.group(0)
    if m.group(4):
        d = int(m.group(4))
        if d in _DENOMS and 0 < a < d:
            return _fmt(a / d)
        return m.group(0)
    return m.group(0)


def _fmt(x: float) -> str:
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return s or "0"


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, fractions et virgules décimales
    normalisées, « 4x8 » → « 4 x 8 », synonymes appliqués."""
    s = (texte or "").lower().replace("œ", "oe").replace("æ", "ae")
    s = _sans_accents(s)
    s = s.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    # Marques de pouce / pied seulement APRÈS un nombre (« 12" », « 8' »,
    # « 4'x8' ») ; ailleurs l'apostrophe est une élision (« d'épinette »).
    s = re.sub(r"(?<=\d)\s*(?:''|\"|\u2033)", " po ", s)
    s = re.sub(r"(?<=\d)\s*(?:'|\u2019|\u2032)", " pi ", s)
    s = s.replace("\u2019", " ").replace("'", " ").replace('"', " ")
    # Expressions à plusieurs mots → un jeton (avant tout découpage).
    for expr, rep_ in _EXPRESSIONS:
        s = s.replace(expr, rep_)
    s = _DEC_COMMA_RE.sub(r"\1.\2", s)
    s = _LETTRE_FRACTION_RE.sub(" ", s)
    s = _FRACTION_RE.sub(_fraction, s)
    s = _DIM_RE.sub(" x ", s)
    s = re.sub(r"(?<=[a-z ])x(?=\d)", " x ", s)  # « 4 pi x8 pi »
    s = re.sub(r"(?<=\d)x(?=[a-z ])", " x ", s)
    s = re.sub(r"[^a-z0-9./ ]+", " ", s)
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
        w = w.strip("./")
        if not w:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", w):
            try:
                nombres.add(_fmt(float(w)))
            except ValueError:
                nombres.add(w)
        elif re.fullmatch(r"\d+/\d+", w):
            nombres.add(w)  # calibre « 14/2 » : doit se retrouver tel quel
        elif len(w) >= 3 and w not in _STOP:
            mots.add(w)
    return nombres, mots


def _premier_mot(texte: str) -> Optional[str]:
    """Premier mot significatif du nom du matériau = le produit lui-même
    (« panneau », « vis », « peinture ») ; il doit être dans le titre."""
    for w in normaliser(texte).split():
        w = w.strip("./")
        if w and not re.fullmatch(r"[\d./]+", w) and len(w) >= 3 and w not in _STOP:
            return w
    return None


def _racine(w: str) -> str:
    """Racine grossière (pluriels, féminins) pour comparer « panneaux »
    et « panneau », « isolante » et « isolant »."""
    for suf in ("aux", "eaux", "es", "s", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def score(nom_materiau: str, titre: str) -> float:
    """Score (0-1) d'un titre de produit pour un nom de matériau.

    Règles dures (score 0) : un nombre du matériau absent du titre (une
    dimension absente, c'est un autre produit) ; le premier mot (le
    produit : « panneau », « vis », « tuyau ») absent ; un mot
    significatif absent (« blanc » vs « noir », « galvanisé »). Ensuite :
    pénalité de 0,1 par nombre du titre étranger au matériau (autre
    format, « 2 000/pqt ») et de 0,15 si le titre porte une dimension
    « a x b » que le matériau n'a pas (quart de feuille, autre longueur)."""
    n_m, w_m = _tokens(nom_materiau)
    n_t, w_t = _tokens(titre)
    if not n_m and not w_m:
        return 0.0
    if n_m and not n_m.issubset(n_t):
        return 0.0
    racines_t = {_racine(w) for w in w_t}

    def present(w: str) -> bool:
        if w in w_t or _racine(w) in racines_t:
            return True
        # Abréviation de facture (« adapt », « galv », « epin ») : le mot
        # du matériau est le DÉBUT d'un mot du titre (4 lettres au moins).
        return len(w) >= 4 and any(t.startswith(w) for t in w_t)

    premier = _premier_mot(nom_materiau)
    if premier and not present(premier):
        return 0.0
    if any(not present(w) for w in w_m):
        return 0.0
    penalite = min(0.3, 0.1 * len(n_t - n_m))
    if not re.search(r"\d x \d", normaliser(nom_materiau)) and re.search(r"\d x \d", normaliser(titre)):
        penalite += 0.15
    return round(max(0.0, 1.0 - penalite), 3)


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


def requetes_mots(nom: str) -> list[str]:
    """Requêtes « par mot », sans les nombres : d'abord tous les mots
    significatifs (« alimentation toilette »), puis le produit seul avec
    sa marque (« epinette », « peinture glidden »). Le site renvoie alors
    toutes les grandeurs, et le notateur retient celle dont les nombres
    correspondent — « épinette 2x6 » → « epinette » → la 2 x 6."""
    premier = _premier_mot(nom)
    if not premier:
        return []
    out: list[str] = []
    mots_ordre: list[str] = []
    for w in normaliser(nom).split():
        w = w.strip("./")
        if w and not re.fullmatch(r"[\d./]+", w) and len(w) >= 3 and w not in _STOP and w not in mots_ordre:
            mots_ordre.append(w)
    if len(mots_ordre) > 1:
        out.append(" ".join(mots_ordre))
    seul = [premier] + [m for m in sorted(_marques(nom)) if m and m != premier]
    q = " ".join(seul)
    if q.lower() not in {x.lower() for x in out}:
        out.append(q)
    return out


def requete_mot(nom: str) -> Optional[str]:
    """Le produit seul (dernière requête « par mot »)."""
    qs = requetes_mots(nom)
    return qs[-1] if qs else None


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
