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

from typing import Any, List, Optional

from app.integrations.ip_geo import ip_publique, position_par_ip

#: Préfixe d'une position déduite de l'adresse internet.
APPROX = "~"
#: En-têtes où un relais (Render, Cloudflare, Vercel) met l'adresse du client.
_ENTETES_IP = ("x-forwarded-for", "true-client-ip", "cf-connecting-ip", "x-real-ip")


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


def candidats_ip(request: Any, declaree: Optional[str] = None) -> List[str]:
    """Adresses possibles du téléphone, dans l'ordre de confiance : celle
    que l'app a déclarée, puis les en-têtes des relais (toutes les entrées
    de ``X-Forwarded-For`` : l'app passe par le serveur Next.js avant
    l'API, donc la première peut être un relais interne), puis la
    connexion."""
    bruts: List[str] = [declaree or ""]
    if request is not None:
        for nom in _ENTETES_IP:
            bruts.extend((request.headers.get(nom) or "").split(","))
        bruts.append(request.client.host if request.client else "")
    return [b.strip()[:64] for b in bruts if b and b.strip()]


def ip_client(request: Any, declaree: Optional[str] = None) -> Optional[str]:
    """Première adresse PUBLIQUE parmi les candidates, sinon None."""
    for candidat in candidats_ip(request, declaree):
        publique = ip_publique(candidat)
        if publique:
            return publique
    return None


async def position_ou_approx(
    exacte: Optional[str],
    request: Any,
    approx_client: Optional[str] = None,
    ip_declaree: Optional[str] = None,
) -> Optional[str]:
    """La position GPS reçue ; sinon l'approximation que le téléphone a
    obtenue lui-même de son adresse internet ; sinon celle que l'API
    déduit de l'adresse (déclarée par l'app ou vue par les relais) ;
    sinon None. Ne bloque jamais le punch."""
    if exacte:
        return exacte
    approx = normaliser(approx_client)
    if approx:
        return f"{APPROX}{approx}"
    coords = await position_par_ip(ip_client(request, ip_declaree))
    if coords is None:
        return None
    return approximative(coords[0], coords[1])


def ajouter_fin(existante: Optional[str], fin: Optional[str]) -> Optional[str]:
    """Ajoute la position de sortie à celle d'entrée (``début|fin``)."""
    if not fin:
        return existante
    debut = (existante or "").split("|")[0]
    return f"{debut}|{fin}"[:128]
