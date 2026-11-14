"""Présentation du pôle Immobilier — interrupteur de retour (2026-11-13).

Steven, avant la mise en place de la refonte d'Immobilier : « avant de
mettre tout en place, on s'assure de pouvoir backer à l'état actuel si
c'est trop difficile d'utilisation ».

D'où ce réglage : les écrans actuels restent dans le code, les nouveaux
sont construits À CÔTÉ, et un interrupteur par lot choisit lequel est
montré. Le réglage est COMMUN à toute l'équipe (un seul Immobilier, pas
un par personne), changé par un admin dans Paramètres → Immobilier →
« Présentation d'Immobilier », sans déploiement. Il ne touche à aucune
donnée : revenir à la présentation actuelle ne perd rien.

Stockage : ``AutomationSetting("immobilier_presentation")``, un booléen
par lot dans ``config_json``. Absence de ligne ou de clé = nouvelle
présentation (défaut des lots livrés). Un lot PAS ENCORE LIVRÉ n'a aucun
effet, quel que soit son réglage : ``actif`` vaut toujours faux pour lui.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from app.models.automation_setting import AutomationSetting

KEY = "immobilier_presentation"

#: Les lots de la refonte, dans l'ordre de livraison. ``livre`` passe à
#: vrai dans le commit qui livre les écrans du lot.
LOTS: tuple[dict[str, Any], ...] = (
    {
        "cle": "menu",
        "titre": "Menu et page « Aujourd'hui »",
        "description": (
            "Menu en quatre blocs (Au quotidien, Portefeuille, Baux, "
            "Argent), nouveaux noms des pages et page « Aujourd'hui » : "
            "une seule liste de choses à faire."
        ),
        "livre": True,
    },
    {
        "cle": "loyers",
        "titre": "Écran des loyers",
        "description": (
            "Une carte par locataire sur cellulaire, un seul bouton "
            "principal par ligne, annulation pendant 10 secondes."
        ),
        "livre": True,
    },
    {
        "cle": "baux",
        "titre": "Baux et logements à louer",
        "description": (
            "Un seul « Nouveau bail » qui demande la situation, tuiles "
            "qui filtrent les baux, un bouton principal par ligne, "
            "tableau des logements à louer qui tient dans l'écran."
        ),
        "livre": True,
    },
    {
        "cle": "fiches",
        "titre": "Fiches immeuble, logement et locataire",
        "description": (
            "Sept onglets sur la fiche immeuble, quatre sur la fiche "
            "locataire, même forme pour la fiche logement, et le bouton "
            "Aide rangé dans la barre du haut."
        ),
        "livre": True,
    },
    {
        "cle": "suivis",
        "titre": "Suivis annuels, dépôts et finances",
        "description": (
            "Suivis annuels ouverts sur « À envoyer », dépôts sans les "
            "baux sans dépôt, Finances et Frais de gestion en deux onglets."
        ),
        "livre": False,
    },
)

CLES: tuple[str, ...] = tuple(lot["cle"] for lot in LOTS)


def normaliser(cfg: Any) -> dict[str, bool]:
    """Un booléen par lot ; toute valeur absente ou illisible = nouvelle
    présentation (le défaut)."""
    source = cfg if isinstance(cfg, dict) else {}
    propre: dict[str, bool] = {}
    for cle in CLES:
        valeur = source.get(cle, True)
        propre[cle] = valeur if isinstance(valeur, bool) else True
    return propre


def actifs(reglages: dict[str, bool]) -> dict[str, bool]:
    """Ce que les écrans doivent VRAIMENT montrer : la nouvelle
    présentation seulement pour un lot livré ET réglé sur « nouvelle »."""
    return {
        lot["cle"]: bool(lot["livre"]) and bool(reglages.get(lot["cle"], True))
        for lot in LOTS
    }


async def charger(db) -> dict[str, bool]:
    row = await db.get(AutomationSetting, KEY)
    if not row or not row.config_json:
        return normaliser({})
    try:
        return normaliser(json.loads(row.config_json))
    except Exception:  # noqa: BLE001 — réglage illisible = défaut
        return normaliser({})


async def enregistrer(
    db, changements: dict[str, bool], *, user_id: Optional[int] = None
) -> dict[str, bool]:
    """Applique les changements par-dessus le réglage courant.
    N'appelle pas commit."""
    courant = await charger(db)
    for cle, valeur in changements.items():
        if cle in CLES and isinstance(valeur, bool):
            courant[cle] = valeur
    row = await db.get(AutomationSetting, KEY)
    if row is None:
        row = AutomationSetting(key=KEY, enabled=True)
        db.add(row)
    row.config_json = json.dumps(courant, ensure_ascii=False)
    if user_id is not None:
        row.updated_by_user_id = user_id
    await db.flush()
    return courant


async def etat(db) -> dict[str, Any]:
    """Le réglage tel que l'écran de Paramètres et les pages le lisent."""
    reglages = await charger(db)
    act = actifs(reglages)
    row = await db.get(AutomationSetting, KEY)
    modifie_le: Optional[datetime] = None
    modifie_par: Optional[str] = None
    if row is not None and row.config_json:
        modifie_le = row.updated_at
        if row.updated_by_user_id:
            from app.models.user import User

            auteur = await db.get(User, row.updated_by_user_id)
            modifie_par = getattr(auteur, "display_name", None) if auteur else None
    return {
        "lots": [
            {
                "cle": lot["cle"],
                "titre": lot["titre"],
                "description": lot["description"],
                "livre": bool(lot["livre"]),
                "nouvelle": reglages[lot["cle"]],
            }
            for lot in LOTS
        ],
        "actif": act,
        "modifie_le": modifie_le,
        "modifie_par": modifie_par,
    }
