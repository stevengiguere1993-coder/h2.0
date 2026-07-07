"""CAPTCHA maison pour le formulaire public de contact.

Défi « cliquez sur la bonne icône » émis et vérifié côté serveur :
GET /api/v1/contact/captcha renvoie une question + 6 icônes et un jeton
signé (HMAC avec jwt_secret) qui encode la bonne réponse SANS la
révéler au client. Le POST public doit renvoyer jeton + réponse ; un
défi absent, expiré, rejoué ou mal résolu classe la demande en « spam »
(silencieux — le bot reçoit l'accusé normal, révisable dans le CRM).

Aucun service externe (reCAPTCHA / Turnstile) : rien à configurer,
aucune dépendance réseau, aucune clé à créer. Un bot qui POST
directement l'API sans passer par le formulaire échoue toujours.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, Optional

# Durée de vie généreuse : un prospect qui laisse le formulaire ouvert
# et le remplit lentement ne doit pas être classé spam. L'anti-rejeu
# (jeton à usage unique) empêche un bot de recycler un défi résolu.
_TTL_SECONDS = 2 * 60 * 60
_OPTIONS_PER_CHALLENGE = 6

# (id, icône, libellé FR, libellé EN)
_ICONS = [
    ("maison", "🏠", "la maison", "the house"),
    ("marteau", "🔨", "le marteau", "the hammer"),
    ("arbre", "🌳", "l'arbre", "the tree"),
    ("voiture", "🚗", "la voiture", "the car"),
    ("chat", "🐱", "le chat", "the cat"),
    ("cle", "🔑", "la clé", "the key"),
    ("echelle", "🪜", "l'échelle", "the ladder"),
    ("pinceau", "🖌️", "le pinceau", "the paintbrush"),
    ("fleur", "🌻", "la fleur", "the flower"),
    ("camion", "🚚", "le camion", "the truck"),
]

# Anti-rejeu best-effort : nonces déjà consommés (mémoire process,
# suffisant en mono-instance ; purgé à l'expiration).
_used_nonces: Dict[str, float] = {}


def _sign(payload: bytes) -> str:
    from app.core.config import settings

    return hmac.new(
        settings.jwt_secret.encode(), payload, hashlib.sha256
    ).hexdigest()


def generate_challenge() -> Dict[str, Any]:
    rng = secrets.SystemRandom()
    picks = rng.sample(_ICONS, _OPTIONS_PER_CHALLENGE)
    target = rng.choice(picks)
    payload = {
        "a": target[0],
        "n": secrets.token_urlsafe(12),
        "exp": int(time.time()) + _TTL_SECONDS,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    token = base64.urlsafe_b64encode(raw).decode() + "." + _sign(raw)
    return {
        "token": token,
        "question_fr": f"Vérification anti-robot : cliquez sur {target[2]}",
        "question_en": f"Anti-robot check: click on {target[3]}",
        "options": [{"id": i, "icon": icon} for i, icon, _fr, _en in picks],
    }


def verify_captcha(token: Optional[str], answer: Optional[str]) -> bool:
    """Vrai si le jeton est signé par nous, non expiré, jamais utilisé,
    et que la réponse est la bonne icône. Consomme le jeton (usage
    unique) dès que la signature est valide, bonne réponse ou non."""
    if not token or not answer or "." not in token:
        return False
    b64, sig = token.rsplit(".", 1)
    try:
        raw = base64.urlsafe_b64decode(b64.encode())
    except Exception:  # noqa: BLE001
        return False
    if not hmac.compare_digest(_sign(raw), sig):
        return False
    try:
        payload = json.loads(raw)
    except Exception:  # noqa: BLE001
        return False
    now = time.time()
    exp = float(payload.get("exp") or 0)
    if exp < now:
        return False
    nonce = str(payload.get("n") or "")
    if not nonce or nonce in _used_nonces:
        return False
    if len(_used_nonces) > 5000:
        for k, k_exp in list(_used_nonces.items()):
            if k_exp < now:
                _used_nonces.pop(k, None)
    _used_nonces[nonce] = exp
    return str(payload.get("a") or "") == (answer or "").strip()
