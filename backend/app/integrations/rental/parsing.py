"""Parsers communs pour annonces de location.

Extracteurs :
- phone numbers (regex toléranant les formats CA)
- nb chambres (« 3 1/2 », « 4½ », « 2 bdrm », …)
- prix (« 1 450 $/mois », « $1,450 », …)
- adresse civique (« 4520 boul. Saint-Laurent », …)
"""

from __future__ import annotations

import re
from typing import List, Optional


# Téléphone canadien : (514) 123-4567, 514-123-4567, 514.123.4567,
# +1 514 123 4567, 1-514-123-4567. On évite les patterns qui
# matchent un code postal ou un montant en $.
_PHONE_RE = re.compile(
    r"""(?<!\d)
    (?:\+?1[\s\-.]?)?              # préfixe pays
    \(?(\d{3})\)?[\s\-.]?           # area code
    (\d{3})[\s\-.]?                 # central
    (\d{4})                          # subscriber
    (?!\d)""",
    re.VERBOSE,
)

# Au Québec les indicatifs valides sont : 418, 438, 450, 514, 579,
# 581, 819, 873. On filtre pour éviter les faux positifs (ex:
# « 9999 999 9999 » dans une description).
_VALID_QC_AREA_CODES = {
    "418", "438", "450", "514", "579", "581", "819", "873",
}


def extract_phones(text: str, *, qc_only: bool = True) -> List[str]:
    """Retourne tous les téléphones trouvés dans le texte, formatés
    en `(XXX) XXX-XXXX`. Si `qc_only`, filtre aux indicatifs Québec.

    Déduplique. Ordre = ordre d'apparition dans le texte.
    """
    if not text:
        return []
    found: List[str] = []
    seen: set[str] = set()
    for m in _PHONE_RE.finditer(text):
        area, central, subscriber = m.group(1), m.group(2), m.group(3)
        if qc_only and area not in _VALID_QC_AREA_CODES:
            continue
        formatted = f"({area}) {central}-{subscriber}"
        if formatted not in seen:
            seen.add(formatted)
            found.append(formatted)
    return found


# Format québécois : « 4 1/2 », « 5½ », « 31/2 », « 4 1/2 sdb »
# Convention : N 1/2 = N-1 chambres + cuisine + salle de bain.
# Ex : 4½ = 2 chambres ; 5½ = 3 chambres ; 3½ = 1 chambre ; 2½ = studio.
_PIECES_RE = re.compile(
    r"""(?<![\d.])         # pas un nombre plus grand
        (\d)               # chiffre des pièces (1-9)
        \s*
        (?:1/2|½|1⁄2)      # demi
        (?![\d])           # pas suivi de chiffre
    """,
    re.VERBOSE,
)

# Anglo : « 2 bedroom », « 3-bdrm », « bedroom: 2 »
_BED_EN_RE = re.compile(
    r"""(\d)\s*(?:bedroom|bdrm|bed\.?|bd\.?)""",
    re.IGNORECASE,
)


def extract_bedrooms(text: str) -> Optional[int]:
    """Extrait le nb de chambres à coucher.

    Convention :
    - « 2½ » → 0 (studio)
    - « 3½ » → 1
    - « 4½ » → 2
    - « 5½ » → 3
    - « 6½ » → 4
    - « 2 bedroom » → 2 (anglo direct)

    Retourne le PREMIER match (les annonces typiques mentionnent
    le nb de pièces en titre ou tout début de description).
    """
    if not text:
        return None
    m = _PIECES_RE.search(text)
    if m:
        n = int(m.group(1))
        # 1½ studio (rare), 2½ = studio, 3½ = 1ch, 4½ = 2ch, etc.
        return max(0, n - 2)
    m = _BED_EN_RE.search(text)
    if m:
        return int(m.group(1))
    return None


# Prix : on EXIGE un indicateur $ ou /mois autour du nombre, sinon
# on confondrait avec un numéro civique ou code postal. Variantes :
# « 1 450 $ », « $1,450 », « 1450$/mois », « 1 450,00 $/mois »,
# « 1 450 par mois », « 1450/mois »
_PRICE_PRE_RE = re.compile(
    r"\$\s*(\d{1,2}[\s,]?\d{3}|\d{3,4})(?:[,.]\d{2})?",
)
_PRICE_POST_RE = re.compile(
    r"""(\d{1,2}[\s,]?\d{3}|\d{3,4})(?:[,.]\d{2})?\s*
        (?:\$\s*(?:/?\s*(?:mois|mo)\s*\.?)?|/?\s*mois|par\s*mois)
    """,
    re.VERBOSE | re.IGNORECASE,
)


def extract_price(text: str) -> Optional[float]:
    """Extrait le prix mensuel — exige $ ou /mois pour éviter de
    confondre avec un numéro civique. Cherche le 1er montant entre
    400 et 10 000."""
    if not text:
        return None
    for regex in (_PRICE_PRE_RE, _PRICE_POST_RE):
        for m in regex.finditer(text):
            raw = m.group(1).replace(" ", "").replace(",", "")
            try:
                n = int(raw)
            except ValueError:
                continue
            if 400 <= n <= 10000:
                return float(n)
    return None


# « 1234 rue Saint-Denis », « 4520 boul. Saint-Laurent »
_ADDR_RE = re.compile(
    r"""
    (\d{1,5})\s*[-–]?\s*(\d{0,5})?       # numéro civique (avec range optionnel)
    [\s,]+
    (?:rue|boul|boulevard|av|avenue|ch|chemin|place|route|rang|terrasse|côte)
    \.?\s+
    ([A-ZÀÂÉÊËÎÔÙÛÜÇ][\w\-\s'.àâéêëîïôùûüç]{2,80}?)
    (?=,|\s+(?:H\d|Montr|Laval|Longueuil|Brossard|appart|app|qc|québec|canada)|$)
    """,
    re.VERBOSE | re.IGNORECASE,
)


def extract_address(text: str) -> Optional[dict]:
    """Tente d'extraire (civique, nom_rue) du texte de l'annonce.

    Retourne None si rien de plausible. Sinon { civique, nom_rue }.
    """
    if not text:
        return None
    m = _ADDR_RE.search(text)
    if not m:
        return None
    civique = m.group(1).strip()
    rue = m.group(3).strip()
    if not rue or len(rue) < 3:
        return None
    return {"civique": civique, "nom_rue": rue}


# ============== INCLUSIONS ==============
# Mapping mot-clé → tag normalisé. Regex matche les variantes
# courantes (FR + EN + abrégé).
_INCLUSIONS = (
    ("chauffage", re.compile(
        r"chauff(?:age|é|er|ée)|chauf\.?\s*incl|heat(?:ing)?\s+incl|"
        r"heating\s+included",
        re.IGNORECASE,
    )),
    ("electricite", re.compile(
        r"électricité|electricite|hydro|electricity|elect\.?\s*incl",
        re.IGNORECASE,
    )),
    ("eau_chaude", re.compile(
        r"eau\s*chaude|hot\s*water",
        re.IGNORECASE,
    )),
    ("internet", re.compile(
        r"internet(?:\s+(?:incl|inclus))?|wifi|wi-?fi",
        re.IGNORECASE,
    )),
    ("cable", re.compile(
        r"câble(?:\s+TV)?|cable\s*TV?|tv\s*cable",
        re.IGNORECASE,
    )),
    ("stationnement", re.compile(
        r"stationnement|parking",
        re.IGNORECASE,
    )),
    ("electromenagers", re.compile(
        r"électroménagers?|appareils?\s+ménagers?|"
        r"appliances?(?:\s+included)?|fridge.*stove|frigo.*cuisinière",
        re.IGNORECASE,
    )),
    ("climatiseur", re.compile(
        r"climatiseur|climatisation|air\s*climatisé|"
        r"a\.?c\.?(?!\w)|air\s*conditioning",
        re.IGNORECASE,
    )),
    ("laveuse_secheuse", re.compile(
        r"laveuse|sécheuse|laundry|washer|dryer",
        re.IGNORECASE,
    )),
    ("ascenseur", re.compile(
        r"ascenseur|elevator",
        re.IGNORECASE,
    )),
    ("meuble", re.compile(
        r"meublé|furnished",
        re.IGNORECASE,
    )),
)


def extract_inclusions(text: str) -> list[str]:
    """Détecte les inclusions/équipements mentionnés dans l'annonce.

    Retourne une liste de tags normalisés (ex: ['chauffage',
    'electricite', 'stationnement']). Trié alphabétiquement.
    """
    if not text:
        return []
    found: set[str] = set()
    for tag, pattern in _INCLUSIONS:
        if pattern.search(text):
            found.add(tag)
    return sorted(found)


# ============== ÉTAT (rénové / neuf / standard) ==============
_RENOVATED_RE = re.compile(
    r"""\b(?:
        rénové|renove|renovated?|renov\.?|
        neuf|nouveau|brand[\s-]?new|
        refait\s+(?:à|a)\s+neuf|
        complèt(?:ement|ement)\s+rénové|
        modernisé|moderne|moderniz(?:ed|er)
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)


def is_renovated(text: str) -> bool:
    """Détecte si l'annonce mentionne un état rénové/neuf.

    Mots-clés : rénové, refait à neuf, neuf, modernisé, etc.
    Heuristique simple — un faux positif possible si « pas rénové »
    apparaît, mais c'est rare dans les annonces.
    """
    if not text:
        return False
    return bool(_RENOVATED_RE.search(text))


# ============== QUARTIER (Montréal et grands centres) ==============
# Liste non-exhaustive des quartiers les plus communs des grands
# centres québécois. On cherche dans le texte (case-insensitive)
# le 1er match.
_QUARTIERS = (
    # Île de Montréal
    "Plateau Mont-Royal", "Plateau-Mont-Royal", "Plateau",
    "Mile End", "Mile-End",
    "Outremont",
    "Westmount",
    "Notre-Dame-de-Grâce", "NDG",
    "Côte-des-Neiges", "Cote-des-Neiges", "CDN",
    "Hochelaga-Maisonneuve", "Hochelaga", "HoMa",
    "Rosemont", "Rosemont-La-Petite-Patrie", "Petite-Patrie",
    "Villeray", "Villeray-Saint-Michel-Parc-Extension",
    "Ahuntsic", "Ahuntsic-Cartierville",
    "Saint-Henri", "St-Henri",
    "Saint-Léonard", "St-Léonard", "St-Leonard",
    "Verdun", "Île-des-Sœurs",
    "LaSalle", "Lachine",
    "Pointe-aux-Trembles", "PAT",
    "Mercier", "Anjou",
    "Vieux-Montréal", "Vieux Montréal",
    "Centre-Ville", "Centre-ville", "Downtown",
    "Saint-Michel", "Saint Michel",
    "Le Sud-Ouest", "Sud-Ouest", "Petite-Bourgogne", "Pointe-Saint-Charles",
    "Griffintown",
    # Hors île
    "Laval", "Chomedey", "Sainte-Dorothée", "Pont-Viau", "Auteuil",
    "Longueuil", "Brossard", "Saint-Lambert", "Saint-Hubert",
    "Boucherville", "Saint-Bruno",
    "Terrebonne", "Mascouche", "Repentigny",
    "Blainville", "Sainte-Thérèse", "Boisbriand",
    "Saint-Eustache", "Deux-Montagnes",
)


def extract_quartier(text: str) -> Optional[str]:
    """Trouve un quartier connu mentionné dans l'annonce.

    Retourne la forme canonique normalisée (ex: « Plateau »
    pour toutes les variantes Plateau / Plateau Mont-Royal /
    Plateau-Mont-Royal).
    """
    if not text:
        return None
    # Normalisation des variantes vers une forme canonique.
    canonical = {
        "plateau-mont-royal": "Plateau Mont-Royal",
        "plateau mont-royal": "Plateau Mont-Royal",
        "plateau": "Plateau Mont-Royal",
        "mile-end": "Mile End",
        "mile end": "Mile End",
        "ndg": "Notre-Dame-de-Grâce",
        "notre-dame-de-grâce": "Notre-Dame-de-Grâce",
        "cdn": "Côte-des-Neiges",
        "cote-des-neiges": "Côte-des-Neiges",
        "côte-des-neiges": "Côte-des-Neiges",
        "homa": "Hochelaga-Maisonneuve",
        "hochelaga": "Hochelaga-Maisonneuve",
        "hochelaga-maisonneuve": "Hochelaga-Maisonneuve",
        "petite-patrie": "Rosemont",
        "rosemont-la-petite-patrie": "Rosemont",
        "st-henri": "Saint-Henri",
        "saint-henri": "Saint-Henri",
        "st-léonard": "Saint-Léonard",
        "st-leonard": "Saint-Léonard",
        "saint-léonard": "Saint-Léonard",
        "pat": "Pointe-aux-Trembles",
        "pointe-aux-trembles": "Pointe-aux-Trembles",
        "vieux montréal": "Vieux-Montréal",
        "vieux-montréal": "Vieux-Montréal",
        "centre-ville": "Centre-Ville",
        "downtown": "Centre-Ville",
        "sud-ouest": "Le Sud-Ouest",
        "le sud-ouest": "Le Sud-Ouest",
        "petite-bourgogne": "Le Sud-Ouest",
        "pointe-saint-charles": "Le Sud-Ouest",
        "griffintown": "Griffintown",
    }

    text_low = text.lower()
    # On cherche d'abord les noms LONGS pour éviter qu'un nom court
    # ne shadow un nom long. Trié par longueur descendante.
    for q in sorted(_QUARTIERS, key=len, reverse=True):
        if q.lower() in text_low:
            return canonical.get(q.lower(), q)
    return None
