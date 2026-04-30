"""Mapping des codes MAMH (Ministère des Affaires municipales et de
l'Habitation) vers les noms de municipalités.

Les fichiers XML du rôle d'évaluation foncière du Québec sont nommés
selon le pattern :
    RL{code_mamh:5}_{annee}.xml      → ex. RL66023_2026.xml = Montréal
    RLNR{n:3}_{annee}.xml            → catégorie spéciale (chemins de
                                        fer, télécoms, hydro, gaz…)

Le code MAMH (5 chiffres) identifie la municipalité de façon unique.
Mapping enrichi à mesure que les imports révèlent de nouveaux codes.
"""

from __future__ import annotations

import re
from typing import Optional


# Codes MAMH des principales municipalités proches de Montréal
# (rayon ~80 km). Source : Répertoire des municipalités du Québec.
_CODE_TO_NAME: dict[str, str] = {
    # Île de Montréal et villes liées
    "66023": "Montréal",
    "66032": "Montréal-Est",
    "66058": "Westmount",
    "66062": "Côte-Saint-Luc",
    "66072": "Hampstead",
    "66087": "Montréal-Ouest",
    "66097": "Mont-Royal",
    "66107": "Outremont",
    "66112": "Dorval",
    "66117": "Pointe-Claire",
    "66097": "Mont-Royal",
    "66127": "Kirkland",
    "66087": "Montréal-Ouest",
    "66142": "Beaconsfield",
    "66097": "Mont-Royal",
    "66157": "Baie-D'Urfé",
    "66072": "Hampstead",
    "66162": "Sainte-Anne-de-Bellevue",
    "66097": "Mont-Royal",
    "66167": "Senneville",
    # Laval
    "65005": "Laval",
    # Rive-Sud (Montérégie)
    "58007": "Saint-Lambert",
    "58037": "Brossard",
    "58072": "Saint-Bruno-de-Montarville",
    "58227": "Longueuil",
    "58033": "Boucherville",
    "57040": "La Prairie",
    "57010": "Candiac",
    "57020": "Delson",
    "57045": "Saint-Philippe",
    "57050": "Saint-Mathieu",
    "57033": "Saint-Constant",
    "57005": "Sainte-Catherine",
    "57067": "Léry",
    "57105": "Châteauguay",
    "57033": "Saint-Constant",
    "57100": "Mercier",
    "55008": "Carignan",
    "55023": "Chambly",
    "55037": "Richelieu",
    "55048": "Marieville",
    "57030": "Sainte-Martine",
    "56083": "Mont-Saint-Hilaire",
    "56097": "McMasterville",
    "56102": "Otterburn Park",
    "56083": "Mont-Saint-Hilaire",
    "56078": "Beloeil",
    "53050": "Saint-Jean-sur-Richelieu",
    "57025": "Sainte-Julie",
    # Vaudreuil-Soulanges
    "71005": "Vaudreuil-Dorion",
    "71017": "Pincourt",
    "71022": "L'Île-Perrot",
    "71025": "Notre-Dame-de-l'Île-Perrot",
    "71040": "Saint-Lazare",
    "71060": "Hudson",
    "71095": "Rigaud",
    # Rive-Nord (Laurentides + Lanaudière proches)
    "73005": "Saint-Jérôme",
    "73015": "Saint-Hippolyte",
    "73025": "Bois-des-Filion",
    "73030": "Lorraine",
    "73035": "Rosemère",
    "73040": "Sainte-Thérèse",
    "73045": "Boisbriand",
    "73050": "Blainville",
    "75017": "Mascouche",
    "75005": "Terrebonne",
    "76023": "Repentigny",
    "76020": "Charlemagne",
    "76015": "L'Assomption",
    "76005": "Saint-Sulpice",
    "75025": "Mirabel",
    "75035": "Saint-Eustache",
    "75028": "Deux-Montagnes",
    "75040": "Sainte-Marthe-sur-le-Lac",
    "75017": "Mascouche",
    "75032": "Pointe-Calumet",
    "75050": "Saint-Joseph-du-Lac",
    "72032": "Oka",
    # Hors-périmètre proche (>50km, on les met quand même pour
    # complétude des étiquettes)
    "61027": "Joliette",
    "70022": "Salaberry-de-Valleyfield",
    "47017": "Granby",
    "53052": "Saint-Hyacinthe",
    "49058": "Drummondville",
    "53005": "Sorel-Tracy",
    "78032": "Mont-Tremblant",
    "77022": "Saint-Sauveur",
    "77043": "Sainte-Adèle",
    "78047": "Sainte-Agathe-des-Monts",
}


_FILENAME_RE = re.compile(r"RL(?:NR)?(\d+)_\d{4}\.xml", re.IGNORECASE)


def code_from_filename(filename: str) -> Optional[str]:
    """Extrait le code MAMH (5 chiffres) du nom de fichier.

    RL66023_2026.xml → '66023'
    RLNR942_2026.xml → '942'  (catégorie spéciale, pas une municipalité)
    """
    m = _FILENAME_RE.match(filename or "")
    return m.group(1) if m else None


def code_to_name(code: Optional[str]) -> Optional[str]:
    """Retourne le nom de municipalité pour un code MAMH connu, sinon None.
    Les codes 3-chiffres (RLNR…) ne sont jamais des municipalités."""
    if not code:
        return None
    return _CODE_TO_NAME.get(code)
