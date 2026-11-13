"""Périodes de prix de loyer d'un bail — LA règle « quel loyer pour quel mois ».

Retour Steven / mvilliard (2026-11-13, bug 210) : « le loyer était à 470,
il est maintenant 500 — changer le prix du loyer modifie le calcul des
mois passés ; il faudrait pouvoir mettre des périodes de prix (comme
dans Proprio Expert, une nouvelle période pour la nouvelle entente) ».

Avant : un bail n'avait qu'UN prix (``Bail.loyer_mensuel``) et le solde
se calculait « nombre de mois échus × loyer ». Changer le prix réécrivait
donc tout l'historique dû.

Désormais un bail peut porter une liste de périodes
(``Bail.loyer_periodes_json``) :

    [{"depuis": "2026-07-01", "loyer": 470.0},
     {"depuis": "2026-11-01", "loyer": 500.0}]

- le loyer d'un mois = celui de la DERNIÈRE période commencée à ce mois ;
- aucune période (cas de presque tous les baux) = ``loyer_mensuel`` pour
  toute la durée, exactement comme avant ;
- la première période démarre toujours au début du bail : au premier
  changement, l'ancien prix devient la période d'ouverture ;
- ``loyer_mensuel`` reste le loyer EN VIGUEUR (ce mois-ci) : toutes les
  surfaces qui affichent « le loyer » d'un bail restent justes, et la
  resynchronisation se fait au passage (``synchroniser_loyer_courant``).
"""
from __future__ import annotations

import json
from datetime import date
from typing import Iterable, List, Optional, Tuple

Periode = Tuple[date, float]


def _premier(d: date) -> date:
    return d.replace(day=1)


def mois_suivant(m: date) -> date:
    return date(m.year + (1 if m.month == 12 else 0), 1 if m.month == 12 else m.month + 1, 1)


def lire_periodes(bail) -> List[Periode]:
    """Périodes du bail, triées et dédoublonnées (liste vide = prix
    unique). Une valeur illisible est ignorée plutôt que de casser le
    calcul des soldes."""
    brut = getattr(bail, "loyer_periodes_json", None)
    if not brut:
        return []
    try:
        data = json.loads(brut)
    except (TypeError, ValueError):
        return []
    out: dict[date, float] = {}
    for p in data if isinstance(data, list) else []:
        try:
            d = _premier(date.fromisoformat(str(p["depuis"])[:10]))
            v = round(float(p["loyer"]), 2)
        except (KeyError, TypeError, ValueError):
            continue
        if v < 0:
            continue
        out[d] = v
    return sorted(out.items())


def ecrire_periodes(bail, periodes: Iterable[Periode]) -> None:
    """Enregistre les périodes (une seule période = prix unique : on
    revient à ``loyer_mensuel`` seul, sans JSON)."""
    liste = sorted({_premier(d): round(float(v), 2) for d, v in periodes}.items())
    if len(liste) <= 1:
        bail.loyer_periodes_json = None
        if liste:
            bail.loyer_mensuel = liste[0][1]
        return
    bail.loyer_periodes_json = json.dumps(
        [{"depuis": d.isoformat(), "loyer": v} for d, v in liste]
    )


def loyer_du_mois(bail, mois: date, periodes: Optional[List[Periode]] = None) -> float:
    """Loyer du bail pour le mois ``mois`` (n'importe quel jour du mois)."""
    pers = lire_periodes(bail) if periodes is None else periodes
    base = float(getattr(bail, "loyer_mensuel", 0) or 0)
    if not pers:
        return base
    m = _premier(mois)
    courant: Optional[float] = None
    for d, v in pers:
        if d <= m:
            courant = v
        else:
            break
    # Mois antérieur à la première période (ne devrait pas arriver : elle
    # démarre au début du bail) → prix de la première période.
    return pers[0][1] if courant is None else courant


def loyers_entre(bail, debut: date, fin: date) -> float:
    """Somme des loyers des mois ``debut`` → ``fin`` inclus (1ers du mois)."""
    pers = lire_periodes(bail)
    m, fin = _premier(debut), _premier(fin)
    if fin < m:
        return 0.0
    if not pers:
        n = (fin.year - m.year) * 12 + (fin.month - m.month) + 1
        return round(n * float(getattr(bail, "loyer_mensuel", 0) or 0), 2)
    total = 0.0
    while m <= fin:
        total += loyer_du_mois(bail, m, pers)
        m = mois_suivant(m)
    return round(total, 2)


def synchroniser_loyer_courant(bail, today: date) -> bool:
    """Aligne ``loyer_mensuel`` sur la période en vigueur ce mois-ci.
    Vrai si la valeur a changé (l'appelant décide du commit)."""
    pers = lire_periodes(bail)
    if not pers:
        return False
    v = loyer_du_mois(bail, today, pers)
    if abs(float(bail.loyer_mensuel or 0) - v) < 0.005:
        return False
    bail.loyer_mensuel = v
    return True


def ajouter_periode(bail, depuis: date, loyer: float, today: date) -> List[Periode]:
    """Nouveau prix À PARTIR DU mois ``depuis`` : les mois d'avant gardent
    leur prix. Au premier changement, le prix actuel devient la période
    d'ouverture (début du bail). Un changement daté du début du bail (ou
    avant) remplace le prix d'ouverture : c'est une correction."""
    depuis = _premier(depuis)
    debut_bail = _premier(bail.date_debut) if bail.date_debut else depuis
    pers = dict(lire_periodes(bail))
    if not pers:
        pers[debut_bail] = round(float(bail.loyer_mensuel or 0), 2)
    if depuis <= debut_bail:
        # Correction du prix d'ouverture : la période du début du bail.
        pers.pop(depuis, None)
        pers[debut_bail] = round(float(loyer), 2)
    else:
        pers[depuis] = round(float(loyer), 2)
    ecrire_periodes(bail, pers.items())
    synchroniser_loyer_courant(bail, today)
    return lire_periodes(bail) or [(debut_bail, float(bail.loyer_mensuel or 0))]


def retirer_periode(bail, depuis: date, today: date) -> List[Periode]:
    """Retire le changement de prix daté de ``depuis`` (le mois reprend le
    prix de la période précédente). La période d'ouverture ne se retire
    pas : elle EST le prix du bail."""
    depuis = _premier(depuis)
    pers = lire_periodes(bail)
    if not pers or depuis == pers[0][0]:
        raise ValueError("La première période est le prix de départ du bail — modifie-la plutôt.")
    restantes = [(d, v) for d, v in pers if d != depuis]
    if len(restantes) == len(pers):
        raise LookupError("Aucune période ne commence ce mois-là.")
    ecrire_periodes(bail, restantes)
    synchroniser_loyer_courant(bail, today)
    return lire_periodes(bail) or [(restantes[0][0], float(bail.loyer_mensuel or 0))]


def periodes_affichage(bail) -> List[dict]:
    """Périodes pour l'API : toujours au moins une (le prix unique)."""
    pers = lire_periodes(bail)
    if not pers:
        d = _premier(bail.date_debut) if getattr(bail, "date_debut", None) else None
        return [{"depuis": d.isoformat() if d else None, "loyer": float(bail.loyer_mensuel or 0)}]
    return [{"depuis": d.isoformat(), "loyer": v} for d, v in pers]


__all__ = [
    "ajouter_periode",
    "ecrire_periodes",
    "lire_periodes",
    "loyer_du_mois",
    "loyers_entre",
    "mois_suivant",
    "periodes_affichage",
    "retirer_periode",
    "synchroniser_loyer_courant",
]
