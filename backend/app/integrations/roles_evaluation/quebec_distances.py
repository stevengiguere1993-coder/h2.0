"""Distance approximative en km de chaque municipalité au centre-ville
de Montréal (45.5017° N, 73.5673° W = Place Ville-Marie / centre-ville).

Calculée à partir des centroïdes connus (Wikipedia, fiches officielles
des villes). Précision ±1-2 km — suffisant pour un filtrage par tranches
(< 30 km, 30-50 km, > 50 km).

La clef est le nom normalisé de la municipalité (lower + sans accents,
matchant `_normalize_city()` du module quebec_regional). Si une
municipalité n'apparaît pas ici → distance None → exclue des filtres
de distance (sauf l'option « Toutes »).

Maintenir cette liste à la main quand on importe de nouveaux rôles
qui contiennent des municipalités absentes.
"""

from __future__ import annotations

import unicodedata
from typing import Dict, Optional


def _norm(s: str) -> str:
    if not s:
        return ""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(
        c for c in nfd if not unicodedata.combining(c)
    ).lower().strip()


# Distance en km depuis le centre-ville de Montréal (PVM).
# Source: centroïdes Wikipédia / Open Data Québec, arrondi à 1 km.
_DIST_KM_RAW: Dict[str, float] = {
    # Île de Montréal — ville centrale + arrondissements (~0-20 km)
    "montréal": 0,
    "montreal": 0,
    "ahuntsic-cartierville": 8,
    "anjou": 12,
    "côte-des-neiges-notre-dame-de-grâce": 5,
    "côte-des-neiges–notre-dame-de-grâce": 5,
    "cote-des-neiges-notre-dame-de-grace": 5,
    "lachine": 14,
    "lasalle": 13,
    "le plateau-mont-royal": 3,
    "plateau-mont-royal": 3,
    "le sud-ouest": 4,
    "sud-ouest": 4,
    "mercier-hochelaga-maisonneuve": 6,
    "mercier–hochelaga-maisonneuve": 6,
    "montréal-nord": 12,
    "montreal-nord": 12,
    "pierrefonds-roxboro": 21,
    "rivière-des-prairies-pointe-aux-trembles": 17,
    "riviere-des-prairies-pointe-aux-trembles": 17,
    "rosemont-la petite-patrie": 5,
    "rosemont–la petite-patrie": 5,
    "saint-laurent": 11,
    "saint-léonard": 9,
    "saint-leonard": 9,
    "verdun": 8,
    "ville-marie": 1,
    "villeray-saint-michel-parc-extension": 6,
    "villeray–saint-michel–parc-extension": 6,
    # Île de Montréal — villes liées (enclaves)
    "montréal-est": 13,
    "montreal-est": 13,
    "montréal-ouest": 11,
    "montreal-ouest": 11,
    "westmount": 4,
    "outremont": 5,
    "mont-royal": 7,
    "ville mont-royal": 7,
    "côte-saint-luc": 12,
    "cote-saint-luc": 12,
    "hampstead": 9,
    "dorval": 18,
    "pointe-claire": 22,
    "kirkland": 25,
    "beaconsfield": 27,
    "baie-d'urfé": 30,
    "baie-d-urfe": 30,
    "sainte-anne-de-bellevue": 33,
    "senneville": 33,
    "l'ile-bizard": 23,
    "l'île-bizard-sainte-geneviève": 23,
    "ile-bizard - sainte-genevieve": 23,
    # Laval (~10-25 km)
    "laval": 14,
    # Rive-Sud (~10-30 km)
    "longueuil": 8,
    "saint-lambert": 6,
    "brossard": 12,
    "saint-bruno-de-montarville": 22,
    "boucherville": 17,
    "sainte-julie": 28,
    "saint-basile-le-grand": 30,
    "saint-mathieu-de-beloeil": 32,
    "beloeil": 35,
    "mont-saint-hilaire": 36,
    "mc masterville": 35,
    "mc-masterville": 35,
    "otterburn park": 38,
    "carignan": 28,
    "chambly": 30,
    "richelieu": 35,
    "marieville": 45,
    "saint-jean-sur-richelieu": 42,
    "iberville": 42,
    "saint-luc": 40,
    "la prairie": 17,
    "candiac": 20,
    "delson": 22,
    "saint-philippe": 24,
    "saint-mathieu": 24,
    "saint-constant": 22,
    "sainte-catherine": 18,
    "saint-isidore": 28,
    "léry": 28,
    "chateauguay": 24,
    "châteauguay": 24,
    "mercier": 30,
    "saint-rémi": 38,
    "kahnawake": 17,
    "kanesatake": 35,
    "vaudreuil-dorion": 35,
    "l'ile-perrot": 30,
    "pincourt": 32,
    "terrasse-vaudreuil": 33,
    "notre-dame-de-l'ile-perrot": 32,
    "saint-lazare": 42,
    "hudson": 47,
    "rigaud": 60,
    # Rive-Nord (~15-50 km)
    "boisbriand": 25,
    "rosemère": 23,
    "rosemere": 23,
    "lorraine": 26,
    "bois-des-filion": 25,
    "sainte-thérèse": 27,
    "sainte-therese": 27,
    "blainville": 32,
    "terrebonne": 22,
    "mascouche": 28,
    "repentigny": 22,
    "charlemagne": 18,
    "l'assomption": 32,
    "saint-sulpice": 35,
    "le gardeur": 22,
    "saint-jérôme": 50,
    "saint-jerome": 50,
    "mirabel": 45,
    "saint-eustache": 27,
    "deux-montagnes": 30,
    "sainte-marthe-sur-le-lac": 32,
    "pointe-calumet": 32,
    "saint-joseph-du-lac": 38,
    "oka": 47,
    "saint-placide": 60,
    "lachute": 70,
    # Périphérie ~50-100 km (utiles pour le filtre 50+)
    "joliette": 60,
    "salaberry-de-valleyfield": 65,
    "valleyfield": 65,
    "granby": 80,
    "sorel-tracy": 75,
    "saint-hyacinthe": 60,
    "drummondville": 100,
    "saint-jean-de-matha": 75,
    "saint-donat": 110,
    "tremblant": 120,
    "saint-sauveur": 75,
    "sainte-adèle": 80,
    "sainte-adele": 80,
    "sainte-agathe-des-monts": 95,
    "val-david": 90,
    "morin-heights": 80,
    "prévost": 60,
    "prevost": 60,
    "piedmont": 65,
}


# Index normalisé pour matching robuste
_DIST_KM: Dict[str, float] = {_norm(k): v for k, v in _DIST_KM_RAW.items()}


# Municipalités strictement situées sur l'île de Montréal
# (1 ville centrale + 14 villes liées). Codes MAMH 66xxx.
# Forme normalisée (sans accents, lowercase) pour matching robuste
# avec le champ municipalite stocké tel quel depuis le CSV/XML.
#
# Note : les 19 arrondissements de la Ville de Montréal n'apparaissent
# PAS séparément dans le rôle d'évaluation MAMH — la municipalité y
# est toujours « Montréal ». Les arrondissements ne servent que côté
# UI (libellé d'adresse) ou pour les imports « Ville de Montréal »
# directs (donnees.montreal.ca) qui sont obsolètes.
MTL_ISLAND_CITIES: set[str] = {
    _norm(name)
    for name in (
        "Montréal",                  # 66023 — incl. tous les arrondissements
        "Montréal-Est",              # 66032
        "Westmount",                 # 66058
        "Côte-Saint-Luc",            # 66062
        "Hampstead",                 # 66072
        "Montréal-Ouest",            # 66087
        "Mont-Royal",                # 66097
        "Outremont",                 # 66107 (cas legacy, devenu arrond.)
        "Dorval",                    # 66112
        "Pointe-Claire",             # 66117
        "Kirkland",                  # 66127
        "Beaconsfield",              # 66142
        "Baie-D'Urfé",               # 66157
        "Sainte-Anne-de-Bellevue",   # 66162
        "Senneville",                # 66167
    )
}


def km_from_mtl(municipalite: Optional[str]) -> Optional[float]:
    """Retourne la distance en km depuis le centre-ville de Montréal,
    ou None si la municipalité est inconnue."""
    if not municipalite:
        return None
    return _DIST_KM.get(_norm(municipalite))


def municipalites_within(max_km: float) -> list[str]:
    """Retourne la liste des noms normalisés des municipalités à
    `max_km` km ou moins de Montréal. Pour bâtir un filtre SQL IN ()."""
    return [name for name, dist in _DIST_KM.items() if dist <= max_km]


def municipalites_between(min_km: float, max_km: float) -> list[str]:
    """Idem mais pour une plage de distance."""
    return [
        name
        for name, dist in _DIST_KM.items()
        if min_km <= dist <= max_km
    ]
