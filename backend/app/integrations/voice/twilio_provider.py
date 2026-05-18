"""Provider voix Twilio.

Implémentation directe sans le SDK officiel (`twilio` PyPI) — on n'a
besoin que de :

1. la **validation de signature** des webhooks entrants
   (HMAC-SHA1 sur URL + paramètres POST triés, base64) ;
2. quelques **appels REST** simples (list/update IncomingPhoneNumbers).

`httpx` est déjà dans requirements.txt, donc pas de nouvelle dépendance.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from typing import Mapping, Optional
from xml.sax.saxutils import escape as xml_escape

import httpx

from app.integrations.voice.provider import VoiceProvider

log = logging.getLogger(__name__)

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"


class TwilioVoiceProvider(VoiceProvider):
    """Implémentation Twilio du `VoiceProvider`."""

    name = "twilio"

    def __init__(self, account_sid: str, auth_token: str, timeout: float = 15.0):
        if not account_sid or not auth_token:
            raise RuntimeError("Twilio account_sid / auth_token manquant")
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "TwilioVoiceProvider":
        sid = os.getenv("TWILIO_ACCOUNT_SID") or ""
        tok = os.getenv("TWILIO_AUTH_TOKEN") or ""
        return cls(account_sid=sid, auth_token=tok)

    # ------------------------------------------------------------------
    # Signature validation
    # ------------------------------------------------------------------

    def validate_webhook_signature(
        self,
        url: str,
        params: Mapping[str, str],
        signature: str,
    ) -> bool:
        """Vérifie X-Twilio-Signature.

        Algorithme officiel :
        https://www.twilio.com/docs/usage/webhooks/webhooks-security

            data = url + ''.join(f"{k}{v}" for k, v in sorted(params.items()))
            mac  = HMAC-SHA1(auth_token, data)
            sig  = base64(mac.digest())

        Les paramètres viennent du POST form-encoded — pas du query string
        (à moins que l'URL configurée chez Twilio en contienne déjà).
        """
        if not signature:
            return False
        data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
        mac = hmac.new(self.auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1)
        expected = base64.b64encode(mac.digest()).decode("ascii")
        return hmac.compare_digest(expected, signature)

    # ------------------------------------------------------------------
    # REST API
    # ------------------------------------------------------------------

    def _auth(self) -> tuple[str, str]:
        return (self.account_sid, self.auth_token)

    async def find_number_sid(self, e164: str) -> Optional[str]:
        """Retourne le PN-SID d'un numéro qu'on possède, ou None."""
        url = (
            f"{TWILIO_API_BASE}/Accounts/{self.account_sid}"
            f"/IncomingPhoneNumbers.json"
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, params={"PhoneNumber": e164}, auth=self._auth())
            resp.raise_for_status()
            data = resp.json()
        numbers = data.get("incoming_phone_numbers") or []
        if not numbers:
            return None
        return numbers[0].get("sid")

    async def configure_number_webhook(
        self,
        provider_sid: str,
        voice_url: str,
        status_callback_url: Optional[str] = None,
    ) -> None:
        """Pointe le numéro sur notre webhook entrant."""
        url = (
            f"{TWILIO_API_BASE}/Accounts/{self.account_sid}"
            f"/IncomingPhoneNumbers/{provider_sid}.json"
        )
        form: dict[str, str] = {
            "VoiceUrl": voice_url,
            "VoiceMethod": "POST",
        }
        if status_callback_url:
            form["StatusCallback"] = status_callback_url
            form["StatusCallbackMethod"] = "POST"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, data=form, auth=self._auth())
            resp.raise_for_status()
            log.info("Twilio number %s configuré (voice_url=%s)", provider_sid, voice_url)

    # ------------------------------------------------------------------
    # TwiML
    # ------------------------------------------------------------------

    def build_forward_response(
        self,
        forward_to_e164: str,
        caller_id: Optional[str] = None,
        timeout_sec: int = 20,
    ) -> str:
        attrs = f' timeout="{int(timeout_sec)}"'
        if caller_id:
            attrs += f' callerId="{xml_escape(caller_id, {chr(34): "&quot;"})}"'
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f"<Dial{attrs}>{xml_escape(forward_to_e164)}</Dial>"
            "</Response>"
        )

    def build_reject_response(self, reason: str = "busy") -> str:
        # `reject reason="busy"` rend une tonalité d'occupation, ce qui
        # est plus discret que `hangup` pour les blocklists.
        r = "busy" if reason not in ("busy", "rejected") else reason
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<Response><Reject reason="{r}"/></Response>'
        )

    # ------------------------------------------------------------------
    # TwiML — Secrétaire IA (Phase 2)
    # ------------------------------------------------------------------

    @staticmethod
    def _voice_for_lang(lang: str) -> str:
        """Polly Neural voice ID pour la langue donnée.

        Polly.Léa-Neural (FR-CA) et Polly.Joanna-Neural (EN-US) sont les
        voix neuronales les plus naturelles dispo dans Twilio sans
        surcoût. Vérifié sur la doc Twilio TTS 2025.
        """
        if lang.startswith("en"):
            return "Polly.Joanna-Neural"
        return "Polly.Léa-Neural"

    def build_say_and_gather(
        self,
        *,
        say: str,
        lang: str,
        action_url: str,
        gather_timeout_sec: int = 5,
        max_speech_sec: int = 12,
    ) -> str:
        """TwiML : la secrétaire parle, puis écoute la réponse.

        Twilio renvoie `SpeechResult` (transcription) + `Confidence` à
        `action_url` quand l'appelant s'arrête de parler ou quand le
        timeout est atteint. `actionOnEmptyResult=true` garantit qu'on
        est rappelé même si l'appelant n'a rien dit (silence) — sinon
        Twilio raccroche.
        """
        voice = self._voice_for_lang(lang)
        say_xml = xml_escape(say)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Gather input="speech" language="{lang}" '
            f'speechTimeout="auto" '
            f'timeout="{int(gather_timeout_sec)}" '
            f'speechModel="phone_call" '
            f'actionOnEmptyResult="true" '
            f'action="{xml_escape(action_url)}" method="POST">'
            f'<Say voice="{voice}" language="{lang}">{say_xml}</Say>'
            "</Gather>"
            # Fallback si Gather sort sans rappel (cas rares) — on
            # raccroche poliment plutôt que de boucler.
            f'<Say voice="{voice}" language="{lang}">'
            f'{xml_escape(_GOODBYE.get(lang, _GOODBYE["fr-CA"]))}</Say>'
            "<Hangup/>"
            "</Response>"
        )

    def build_say_and_dial(
        self,
        *,
        say: str,
        lang: str,
        dial_to_e164: str,
        timeout_sec: int = 20,
    ) -> str:
        """TwiML : la secrétaire annonce le transfert puis <Dial>."""
        voice = self._voice_for_lang(lang)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Say voice="{voice}" language="{lang}">{xml_escape(say)}</Say>'
            f'<Dial timeout="{int(timeout_sec)}">{xml_escape(dial_to_e164)}</Dial>'
            "</Response>"
        )

    def build_say_and_hangup(self, *, say: str, lang: str) -> str:
        """TwiML : la secrétaire dit quelque chose puis raccroche."""
        voice = self._voice_for_lang(lang)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Say voice="{voice}" language="{lang}">{xml_escape(say)}</Say>'
            "<Hangup/>"
            "</Response>"
        )


_GOODBYE = {
    "fr-CA": "Désolée, je n'ai rien entendu. Bonne journée.",
    "en-US": "Sorry, I didn't catch that. Have a good day.",
}
