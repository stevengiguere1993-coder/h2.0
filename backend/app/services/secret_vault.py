"""Chiffrement des secrets du coffre « Abonnements ».

Contrairement à :mod:`app.services.drive_oauth` (dont ``_encrypt`` retombe
sur un base64 NON chiffré quand aucune clé n'est configurée), ce module
**REFUSE** de stocker un secret tant qu'aucune vraie clé Fernet n'est
disponible. Un coffre à mots de passe ne doit jamais écrire un secret en
quasi-clair : mieux vaut une erreur explicite qu'une fausse sécurité.

Clé utilisée (dans l'ordre) :
    1. ``SUBSCRIPTION_ENCRYPTION_KEY`` (dédiée au coffre — recommandé)
    2. ``DRIVE_TOKEN_ENCRYPTION_KEY`` (déjà provisionnée en prod, repli)

Générer une clé :
    python -c "from cryptography.fernet import Fernet; \
               print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class VaultNotConfigured(Exception):
    """Aucune clé de chiffrement valide → on refuse toute opération secrète."""


def _vault_fernet() -> Fernet | None:
    """Retourne une instance Fernet valide, ou None si aucune clé exploitable."""
    key = (
        settings.subscription_encryption_key
        or settings.drive_token_encryption_key
    )
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        # Clé présente mais invalide (mauvais format Fernet) → on considère
        # le coffre comme NON configuré plutôt que de risquer un fallback.
        return None


def vault_available() -> bool:
    """True si on peut réellement chiffrer/déchiffrer (vraie clé Fernet)."""
    return _vault_fernet() is not None


def encrypt_secret(plaintext: str) -> str:
    """Chiffre un secret. Lève :class:`VaultNotConfigured` si pas de clé.

    Le ciphertext est renvoyé en texte (ASCII) prêt à stocker en colonne.
    """
    fernet = _vault_fernet()
    if fernet is None:
        raise VaultNotConfigured(
            "Aucune clé de chiffrement configurée "
            "(SUBSCRIPTION_ENCRYPTION_KEY ou DRIVE_TOKEN_ENCRYPTION_KEY). "
            "Refus de stocker un secret en clair."
        )
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    """Déchiffre un secret stocké. Lève si clé absente ou token invalide."""
    fernet = _vault_fernet()
    if fernet is None:
        raise VaultNotConfigured(
            "Clé de chiffrement absente — impossible de déchiffrer."
        )
    try:
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Déchiffrement échoué (la clé a probablement changé)."
        ) from exc
