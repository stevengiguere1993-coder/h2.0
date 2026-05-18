"""Abstraction provider voix.

Permet de swap Twilio pour un autre fournisseur (VoIP.ms, Plivo, Telnyx)
sans toucher au code applicatif. Garder cette interface minimaliste —
on n'ajoute une méthode que quand un cas d'usage concret la requiert.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Mapping, Optional


class VoiceProvider(ABC):
    """Interface commune aux providers téléphonie."""

    name: str

    @abstractmethod
    def validate_webhook_signature(
        self,
        url: str,
        params: Mapping[str, str],
        signature: str,
    ) -> bool:
        """Vérifie qu'un webhook entrant provient bien du provider.

        Args:
            url: URL complète sur laquelle le webhook a été reçu (incluant
                les query params s'il y en a).
            params: Paramètres POST form-encoded reçus.
            signature: Valeur du header de signature (ex. X-Twilio-Signature).

        Returns:
            True si la signature est valide.
        """

    @abstractmethod
    async def find_number_sid(self, e164: str) -> Optional[str]:
        """Retourne le SID provider d'un numéro qu'on possède, ou None."""

    @abstractmethod
    async def configure_number_webhook(
        self,
        provider_sid: str,
        voice_url: str,
        status_callback_url: Optional[str] = None,
    ) -> None:
        """Configure l'URL webhook à appeler quand le numéro reçoit un appel."""

    @abstractmethod
    def build_forward_response(
        self,
        forward_to_e164: str,
        caller_id: Optional[str] = None,
        timeout_sec: int = 20,
    ) -> str:
        """Génère la réponse XML/JSON que le provider attend pour forwarder.

        Pour Twilio = TwiML `<Response><Dial>…</Dial></Response>`.
        """

    @abstractmethod
    def build_reject_response(self, reason: str = "busy") -> str:
        """Génère la réponse pour rejeter l'appel (Phase 3 blocklist)."""
