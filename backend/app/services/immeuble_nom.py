"""Nom affiché d'un immeuble (Steven 2026-11-13).

« Je pense que l'adresse dans le haut devrait être présentée 9085 Millen /
710 Legendre, Montréal » : un immeuble à plusieurs adresses civiques (deux
fiches fusionnées, ou une adresse secondaire saisie à la main) porte dans
son titre TOUTES ses adresses, en forme courte (numéro civique + nom de la
voie), séparées par « / », puis la ville.

Un immeuble à une seule adresse garde son nom automatique habituel
(« adresse, ville »). Un nom que l'utilisateur a écrit lui-même n'est
jamais remplacé : seul un nom encore AUTOMATIQUE suit les adresses
(``nom_est_automatique``).
"""

from __future__ import annotations

import re
from typing import Optional

#: Mots de voie retirés de la forme courte (« Avenue Millen » → « Millen »).
_TYPES_VOIE = (
    "rue", "avenue", "av", "ave", "boulevard", "boul", "blvd", "bd", "chemin",
    "ch", "place", "pl", "rang", "route", "rte", "montée", "montee", "côte",
    "cote", "allée", "allee", "impasse", "croissant", "terrasse", "carré",
    "carre", "cours", "promenade", "ruelle", "square",
)
_RE_TYPE = re.compile(
    r"^(?:" + "|".join(re.escape(t) for t in _TYPES_VOIE) + r")\.?\s+",
    re.IGNORECASE,
)
_RE_ARTICLE = re.compile(r"^(?:de\s+la\s+|de\s+l['’]\s*|du\s+|des\s+|de\s+|d['’]\s*)", re.IGNORECASE)
_RE_CARDINAL = re.compile(r"\s+(?:est|ouest|nord|sud)$", re.IGNORECASE)
_RE_CIVIQUE = re.compile(
    r"^\s*(\d+[A-Za-z]?(?:\s*[-–]\s*\d+[A-Za-z]?)*)\s*,?\s*(.*)$", re.DOTALL
)
_RE_ORDINAL = re.compile(r"^\d+\s*(?:re|er|e|ème|eme|ième|ieme|nd|th)?$", re.IGNORECASE)

LONGUEUR_MAX = 255


def _norm(texte: Optional[str]) -> str:
    """Comparable : casse, ponctuation et espaces ignorés."""
    return " ".join(re.sub(r"[^\w]+", " ", (texte or "").lower()).split())


def adresses_secondaires(address_secondaire: Optional[str]) -> list[str]:
    """Les adresses secondaires d'une fiche (séparées par « · »)."""
    return [m.strip() for m in (address_secondaire or "").split("·") if m.strip()]


def adresse_courte(adresse: Optional[str]) -> str:
    """« 9085, Avenue Millen » → « 9085 Millen » ; « 710, Rue Legendre Est »
    → « 710 Legendre ». Sans numéro civique en tête, ou quand il ne
    resterait qu'un ordinal (« 12e Avenue »), l'adresse est gardée."""
    brut = " ".join((adresse or "").split())
    m = _RE_CIVIQUE.match(brut)
    if not m:
        return brut
    civique = re.sub(r"\s*([-–])\s*", r"\1", m.group(1))
    reste = m.group(2).strip().strip(",").strip()
    if not reste:
        return civique
    court = _RE_TYPE.sub("", reste, count=1)
    if court != reste:
        court = _RE_ARTICLE.sub("", court, count=1)
    court = _RE_CARDINAL.sub("", court).strip().strip(",").strip()
    if not court or _RE_ORDINAL.match(court):
        court = reste.replace(",", "")
    return f"{civique} {court}"


def nom_automatique(
    address: Optional[str],
    city: Optional[str] = None,
    address_secondaire: Optional[str] = None,
) -> str:
    """Le nom donné d'office à une fiche : « adresse, ville » pour une
    adresse ; « 9085 Millen / 710 Legendre, Montréal » pour plusieurs."""
    principale = (address or "").strip()
    ville = (city or "").strip()
    autres = [
        a for a in adresses_secondaires(address_secondaire) if _norm(a) != _norm(principale)
    ]
    if not autres:
        return (f"{principale}, {ville}" if ville else principale)[:LONGUEUR_MAX]
    morceaux: list[str] = []
    for a in [principale] + autres:
        court = adresse_courte(a)
        if court and court not in morceaux:
            morceaux.append(court)
    nom = " / ".join(morceaux)
    return (f"{nom}, {ville}" if ville else nom)[:LONGUEUR_MAX]


def nom_est_automatique(
    name: Optional[str],
    address: Optional[str],
    city: Optional[str] = None,
    address_secondaire: Optional[str] = None,
) -> bool:
    """Vrai si ``name`` est vide ou n'est que l'adresse de la fiche (seule,
    avec la ville, ou en forme multi-adresses) : il peut alors suivre un
    changement d'adresses. Un nom personnalisé renvoie faux."""
    cle = _norm(name)
    if not cle:
        return True
    candidats = {
        _norm(address),
        _norm(nom_automatique(address, city)),
        _norm(nom_automatique(address, None)),
        _norm(nom_automatique(address, city, address_secondaire)),
        _norm(nom_automatique(address, None, address_secondaire)),
    }
    return cle in candidats
