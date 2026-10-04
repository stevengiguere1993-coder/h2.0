"""Codes à usage unique des applications d'authentification (RFC 6238).

Google Authenticator, Microsoft Authenticator, 1Password… : une clé
secrète partagée, un code de 6 chiffres qui change toutes les 30
secondes. Sert de double authentification aux gestes sensibles des
paiements fournisseurs (approuver, créer le fichier de dépôt).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote, urlencode

PERIODE = 30
CHIFFRES = 6


def nouveau_secret() -> str:
    """Clé de 160 bits en base32, sans « = » (format des applications)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _cle(secret: str) -> bytes:
    s = secret.replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def pas_courant(maintenant: Optional[float] = None) -> int:
    return int((time.time() if maintenant is None else maintenant) // PERIODE)


def code_hotp(cle: bytes, compteur: int, chiffres: int = CHIFFRES, algo: str = "sha1") -> str:
    """HOTP (RFC 4226) : troncature dynamique du HMAC du compteur."""
    mac = hmac.new(cle, struct.pack(">Q", compteur), getattr(hashlib, algo)).digest()
    decalage = mac[-1] & 0x0F
    valeur = struct.unpack(">I", mac[decalage : decalage + 4])[0] & 0x7FFFFFFF
    return str(valeur % 10**chiffres).zfill(chiffres)


def code(secret: str, pas: Optional[int] = None) -> str:
    """Code TOTP du pas donné (pas courant par défaut)."""
    return code_hotp(_cle(secret), pas_courant() if pas is None else pas)


def verifier(
    secret: str,
    saisi: str,
    *,
    maintenant: Optional[float] = None,
    fenetre: int = 1,
    dernier_pas: Optional[int] = None,
) -> Optional[int]:
    """Pas de 30 s auquel correspond le code saisi, ou None s'il est faux.

    Tolère un pas d'écart (horloge du téléphone). Un code d'un pas déjà
    utilisé (``dernier_pas``) ou plus ancien est refusé : on ne peut pas
    rejouer un code vu par-dessus l'épaule.
    """
    chiffres = "".join(c for c in (saisi or "") if c.isdigit())
    if len(chiffres) != CHIFFRES:
        return None
    try:
        cle = _cle(secret)
    except (ValueError, TypeError):
        return None
    actuel = pas_courant(maintenant)
    for pas in range(actuel - fenetre, actuel + fenetre + 1):
        if dernier_pas is not None and pas <= dernier_pas:
            continue
        if hmac.compare_digest(code_hotp(cle, pas), chiffres):
            return pas
    return None


def uri(secret: str, compte: str, emetteur: str = "Kratos") -> str:
    """Lien otpauth:// que les applications lisent (code QR ou lien)."""
    etiquette = quote(f"{emetteur}:{compte}", safe="@:")
    params = urlencode(
        {
            "secret": secret,
            "issuer": emetteur,
            "algorithm": "SHA1",
            "digits": CHIFFRES,
            "period": PERIODE,
        }
    )
    return f"otpauth://totp/{etiquette}?{params}"


def qr_svg(contenu: str) -> Optional[str]:
    """Code QR en image SVG (data URI) ; None si ``segno`` est absent : la
    clé reste alors à taper à la main dans l'application."""
    try:
        import segno
    except ImportError:  # pragma: no cover — dépendance de requirements.txt
        return None
    return segno.make(contenu, error="m").svg_data_uri(scale=5, border=2)
