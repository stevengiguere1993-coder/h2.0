"""Loyer EFFECTIF d'un logement — LA hiérarchie (retour client 2026-08-14).

Une seule source de vérité, partagée par toutes les surfaces (listes de
logements, paiements, cashflow, financials) pour en finir avec la
divergence « loyer demandé » / « loyer actuel » :

- Immeuble en GESTION EXTERNE : le loyer SAISI sur le logement
  (``Logement.loyer_demande``) EST la vérité. Un bail résiduel dans
  Kratos (import initial, bascule interne→externe) ne doit JAMAIS le
  masquer — l'onglet Baux est caché en externe, donc un tel bail est
  invisible et inéditable : c'était la cause du « j'enregistre le loyer
  mais il ne se transpose nulle part ».
- Gestion INTERNE, bail ACTIF : le loyer du bail courant fait foi.
  ``loyer_demande`` ne pilote rien — c'est le prix de la PROCHAINE
  location (alimenté par le kanban Locations pendant la vacance).
- Gestion INTERNE, logement vacant : ``loyer_demande`` s'affiche.
"""
from __future__ import annotations

from typing import Optional

#: Statut « occupé » du logement (évite un import circulaire des modèles
#: pour une simple constante).
STATUS_OCCUPE = "occupe"


def loyer_effectif(
    logement,
    loyer_bail: Optional[float],
    gestion_externe: bool,
) -> Optional[float]:
    """Loyer effectif d'un logement selon la hiérarchie ci-dessus.

    ``loyer_bail`` : loyer du/des bail(aux) ACTIF(s) courant(s) du
    logement (somme si location en chambres), ou None s'il n'y en a pas —
    l'appelant le tire de sa propre requête pour rester en batch.
    """
    demande = (
        float(logement.loyer_demande)
        if getattr(logement, "loyer_demande", None) is not None
        else None
    )
    if gestion_externe:
        # Externe : le loyer saisi prime ; un bail résiduel ne sert que
        # de filet quand rien n'a été saisi.
        return demande if demande is not None else loyer_bail
    return loyer_bail if loyer_bail is not None else demande


def loyer_effectif_loue(
    logement,
    loyer_bail: Optional[float],
    gestion_externe: bool,
) -> Optional[float]:
    """Loyer effectif d'une unité LOUÉE — None si l'unité ne rapporte
    rien (ni bail actif, ni statut « occupé »).

    C'est la définition « revenus des unités louées » commune aux
    agrégats (liste des immeubles, P&L, prévisionnel, financials).
    """
    if loyer_bail is None and getattr(logement, "status", None) != STATUS_OCCUPE:
        return None
    return loyer_effectif(logement, loyer_bail, gestion_externe)
