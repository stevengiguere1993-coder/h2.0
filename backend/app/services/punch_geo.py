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

GPS refusé → « on va y aller approximatif » (Steven, 2026-10-29) : la
position est déduite de l'adresse internet du téléphone
(``app.integrations.ip_geo``) et préfixée d'un ``~`` (``"~lat,lng"``)
pour s'afficher comme approximative. Le préfixe n'est jamais accepté de
l'app : seule l'API le pose.
"""

from __future__ import annotations

from typing import Any, Optional

#: Préfixe d'une position déduite de l'adresse internet.
APPROX = "~"


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


def approximative(lat: Optional[float], lng: Optional[float]) -> Optional[str]:
    """``"~lat,lng"`` : position déduite de l'adresse internet."""
    p = position(lat, lng)
    return f"{APPROX}{p}" if p else None


def normaliser(raw: Optional[str]) -> Optional[str]:
    """Texte ``"lat,lng"`` envoyé par l'app → forme normalisée, ou None.
    Un ``~`` envoyé par l'app est refusé : l'approximation vient de l'API."""
    if not raw:
        return None
    texte = str(raw).strip()
    if texte.startswith(APPROX):
        return None
    morceaux = texte.split(",")
    if len(morceaux) != 2:
        return None
    try:
        return position(float(morceaux[0]), float(morceaux[1]))
    except ValueError:
        return None


def ip_client(request: Any) -> Optional[str]:
    """Adresse IP du téléphone derrière Render (premier ``X-Forwarded-For``),
    sinon celle de la connexion."""
    if request is None:
        return None
    brut = request.headers.get("x-forwarded-for") or (
        request.client.host if request.client else None
    )
    if not brut:
        return None
    return brut.split(",")[0].strip()[:64] or None


async def position_ou_approx(exacte: Optional[str], request: Any) -> Optional[str]:
    """La position GPS reçue, sinon l'approximation par adresse internet,
    sinon None. Ne bloque jamais le punch."""
    if exacte:
        return exacte
    from app.integrations.ip_geo import position_par_ip

    coords = await position_par_ip(ip_client(request))
    if coords is None:
        return None
    return approximative(coords[0], coords[1])


def ajouter_fin(existante: Optional[str], fin: Optional[str]) -> Optional[str]:
    """Ajoute la position de sortie à celle d'entrée (``début|fin``)."""
    if not fin:
        return existante
    debut = (existante or "").split("|")[0]
    return f"{debut}|{fin}"[:128]
