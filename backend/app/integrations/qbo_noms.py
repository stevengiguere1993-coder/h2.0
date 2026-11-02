"""Comparer un nom de client Kratos et un nom de client QuickBooks.

Steven (2026-11-02) : « Il se peut que la personne référence et les
courriels soient les mêmes entre les entreprises, nous avons plusieurs
entreprises au même propriétaire. » Le courriel (et la personne
contact) n'identifient donc PAS une compagnie : la fiche « Groupe 1660
Saint-Clément inc. » avait été reliée par son courriel au client QB d'une
autre compagnie du même propriétaire.

Règle : un client QuickBooks retrouvé autrement que par son nom (courriel,
lien mémorisé) n'est le bon que si son NOM est compatible avec celui de la
fiche — même nom aux accents / majuscules / ponctuation près, ou mêmes
mots distinctifs (« Les Constructions ABC inc. » ≡ « Constructions ABC
inc »). Les mots génériques (inc, ltée, groupe, gestion, immobilier…) ne
comptent pas : « Groupe 1660 Saint-Clément inc. » et « Immobilier
Meuser 1 inc. » n'ont aucun mot distinctif en commun.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Set

#: Mots qui font d'un nom celui d'une compagnie (forme normalisée). Ils
#: ne distinguent pas une compagnie d'une autre.
MARQUES_COMPAGNIE = {
    "inc", "ltee", "ltd", "limitee", "limited", "senc", "senrl", "enr",
    "corp", "corporation", "cie", "groupe", "group", "gestion", "immobilier",
    "immobiliere", "immobilieres", "immobiliers", "holding", "holdings",
    "fiducie", "construction", "constructions", "developpement",
    "developpements", "investissement", "investissements", "societe",
    "entreprise", "entreprises", "llc", "co", "services", "syndicat",
    "copropriete", "renovation", "renovations", "placements", "proprietes",
}

_MOTS_VIDES = {"le", "la", "les", "l", "de", "du", "des", "d", "et", "a", "au", "aux", "the", "of", "and"}


def nom_norm(value: Optional[str]) -> str:
    """Nom comparable : minuscules, sans accents, ponctuation réduite à un
    espace (« Saint-Clément inc. » ≡ « saint clement inc »)."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.lower()).split())


def meme_nom(a: Optional[str], b: Optional[str]) -> bool:
    na, nb = nom_norm(a), nom_norm(b)
    return bool(na) and na == nb


def est_compagnie(nom: Optional[str]) -> bool:
    """Nom de compagnie (mot générique ou numéro d'entreprise) plutôt que
    nom de personne."""
    mots = nom_norm(nom).split()
    return any(m in MARQUES_COMPAGNIE for m in mots) or any(
        m.isdigit() and len(m) >= 4 for m in mots
    )


def mots_distinctifs(nom: Optional[str]) -> Set[str]:
    return {
        m for m in nom_norm(nom).split()
        if m not in MARQUES_COMPAGNIE and m not in _MOTS_VIDES
    }


def noms_compatibles(a: Optional[str], b: Optional[str]) -> bool:
    """Vrai si ``a`` et ``b`` désignent vraisemblablement le même client :
    même nom normalisé, mêmes mots distinctifs (ordre indifférent), l'un
    contenu dans l'autre, ou au moins la moitié des mots distinctifs en
    commun."""
    if meme_nom(a, b):
        return True
    ma, mb = mots_distinctifs(a), mots_distinctifs(b)
    if not ma or not mb:
        return False
    if ma <= mb or mb <= ma:
        return True
    return len(ma & mb) / len(ma | mb) >= 0.5


def lien_acceptable(nom_fiche: Optional[str], nom_qb: Optional[str]) -> bool:
    """Un client QB RELIÉ à la fiche (lien mémorisé) mais au nom différent
    reste le bon si les noms sont compatibles, ou s'il s'agit de deux noms
    de personne (fiche d'une personne renommée, faute corrigée). Jamais
    une compagnie au nom incompatible : c'est une autre compagnie."""
    if noms_compatibles(nom_fiche, nom_qb):
        return True
    return not est_compagnie(nom_fiche) and not est_compagnie(nom_qb)
