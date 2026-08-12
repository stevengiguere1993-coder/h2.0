"""Échéance du loyer et seuil de retard — PAR BAIL.

Le bail TAL a une case « le 1er jour du mois » ET un champ « Ou le ___ » :
la quasi-totalité des baux sont payables le 1er, mais pas tous (ex. le
garage du 8900 St-Hubert, payable le 12). Avant, tout le pôle présumait
le 1er et faisait tomber le retard le 5 — ce bail-là apparaissait donc
faussement « en retard » du 5 au 12, chaque mois.

Ce module centralise les deux seules règles qui en découlent :

- ``date_echeance(mois, jour)`` : la date à laquelle le loyer du mois est
  dû (jour borné au dernier jour du mois — un bail au 30 tombe au 28 en
  février) ;
- ``seuil_retard(mois, jour)`` : la date après laquelle un loyer non payé
  est « en retard », soit l'échéance + ``DELAI_GRACE_JOURS``.

Défaut ``jour = 1`` partout : comportement identique à avant pour les
baux existants (échéance le 1er → retard passé le 5).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

#: Délai de grâce du suivi des loyers : échéance le 1er → retard le 5.
DELAI_GRACE_JOURS = 4

#: Délai de grâce du flag ``en_retard`` posé À LA CRÉATION d'un paiement
#: (règle historique « payé plus de 5 jours après l'échéance »). Volon-
#: tairement distinct du seuil d'affichage ci-dessus : on ne stigmatise
#: un paiement encaissé qu'un cran plus tard que la simple alerte.
DELAI_GRACE_PAIEMENT_JOURS = 5

#: Borne haute du jour d'échéance : au-delà, le jour n'existe pas tous
#: les mois (février). Mêmes bornes que la validation des schémas.
JOUR_ECHEANCE_MIN = 1
JOUR_ECHEANCE_MAX = 28


def normaliser_jour(jour: int | None) -> int:
    """Jour d'échéance utilisable : ``None``/hors bornes → 1."""
    try:
        j = int(jour)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1
    if j < JOUR_ECHEANCE_MIN or j > JOUR_ECHEANCE_MAX:
        return 1
    return j


def date_echeance(mois: date, jour: int | None = 1) -> date:
    """Date d'échéance du loyer pour le mois de ``mois`` (1er du mois).

    Le jour est borné au dernier jour réel du mois pour ne jamais lever
    de ``ValueError`` sur février.
    """
    premier = mois.replace(day=1)
    j = normaliser_jour(jour)
    dernier = calendar.monthrange(premier.year, premier.month)[1]
    return premier.replace(day=min(j, dernier))


def seuil_retard(mois: date, jour: int | None = 1) -> date:
    """Date APRÈS laquelle un loyer impayé du mois est « en retard ».

    ``today > seuil_retard(...)`` ⇒ retard. Avec ``jour = 1`` on retrouve
    exactement l'ancien seuil global (le 5 du mois).
    """
    return date_echeance(mois, jour) + timedelta(days=DELAI_GRACE_JOURS)


def paiement_en_retard(
    mois: date, paye_le: date | None, jour: int | None = 1
) -> bool:
    """Le paiement encaissé le ``paye_le`` couvre-t-il un mois en retard ?

    Règle historique conservée telle quelle, simplement ancrée sur
    l'échéance du bail au lieu du 1er du mois.
    """
    if paye_le is None:
        return False
    delta = (paye_le - date_echeance(mois, jour)).days
    return delta > DELAI_GRACE_PAIEMENT_JOURS
