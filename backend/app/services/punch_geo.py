"""Position GPS prise au moment du punch (Steven, 2026-10-26).

Chaque punch (entrée ET sortie) enregistre la position de l'employé,
seulement à ce moment-là — aucun suivi entre les deux. Avis de l'avocat
en droit du travail de Steven : pas d'écran de consentement dans l'app,
puisque la géolocalisation se limite au punch. La permission du système
(navigateur / téléphone) reste demandée par l'OS ; si elle est refusée,
le punch part quand même, sans position.

Format stocké dans ``Punch.geolocation`` : ``"lat,lng"`` au début, puis
``"lat,lng|lat,lng"`` (début|fin) à l'arrêt. Début inconnu et fin connue
→ ``"|lat,lng"``, pour ne jamais confondre la fin avec le début.
"""

from __future__ import annotations

from typing import Optional


def position(lat: Optional[float], lng: Optional[float]) -> Optional[str]:
    """``"lat,lng"`` à 6 décimales, ou None si absent / hors limites."""
    if lat is None or lng is None:
        return None
    try:
        la, ln = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= la <= 90.0 and -180.0 <= ln <= 180.0):
        return None
    if la == 0.0 and ln == 0.0:
        return None
    return f"{la:.6f},{ln:.6f}"


def normaliser(raw: Optional[str]) -> Optional[str]:
    """Texte ``"lat,lng"`` envoyé par l'app → forme normalisée, ou None."""
    if not raw:
        return None
    morceaux = str(raw).strip().split(",")
    if len(morceaux) != 2:
        return None
    try:
        return position(float(morceaux[0]), float(morceaux[1]))
    except ValueError:
        return None


def ajouter_fin(existante: Optional[str], fin: Optional[str]) -> Optional[str]:
    """Ajoute la position de sortie à celle d'entrée (``début|fin``)."""
    if not fin:
        return existante
    debut = (existante or "").split("|")[0]
    return f"{debut}|{fin}"[:128]
