"""Intégration téléphonie — abstraction provider (Twilio par défaut).

Le module expose `get_voice_provider()` qui retourne le provider
configuré. Aujourd'hui : Twilio. Demain : on swap pour VoIP.ms / Plivo /
Telnyx sans toucher au code applicatif.
"""

from app.integrations.voice.provider import VoiceProvider
from app.integrations.voice.twilio_provider import TwilioVoiceProvider


def get_voice_provider() -> VoiceProvider:
    """Retourne le provider voix configuré.

    Lève RuntimeError si les credentials ne sont pas configurés —
    l'appelant doit gérer (typiquement renvoyer 503).
    """
    return TwilioVoiceProvider.from_env()


__all__ = ["VoiceProvider", "TwilioVoiceProvider", "get_voice_provider"]
