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

    async def send_sms(
        self,
        *,
        from_e164: str,
        to_e164: str,
        body: str,
        status_callback_url: Optional[str] = None,
    ) -> dict:
        """Envoie un SMS via l'API REST Twilio. Retourne le payload
        complet (dont MessageSid pour idempotence)."""
        url = f"{TWILIO_API_BASE}/Accounts/{self.account_sid}/Messages.json"
        form: dict[str, str] = {
            "From": from_e164,
            "To": to_e164,
            "Body": body[:1600],  # Twilio segmente automatiquement
        }
        if status_callback_url:
            form["StatusCallback"] = status_callback_url
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, data=form, auth=self._auth())
            resp.raise_for_status()
            return resp.json()

    async def configure_number_sms_webhook(
        self,
        provider_sid: str,
        sms_url: str,
    ) -> None:
        """Pointe le numéro sur notre webhook SMS entrant."""
        url = (
            f"{TWILIO_API_BASE}/Accounts/{self.account_sid}"
            f"/IncomingPhoneNumbers/{provider_sid}.json"
        )
        form = {
            "SmsUrl": sms_url,
            "SmsMethod": "POST",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, data=form, auth=self._auth())
            resp.raise_for_status()
            log.info(
                "Twilio number %s SMS webhook configuré (%s)",
                provider_sid, sms_url,
            )

    async def initiate_outbound_call(
        self,
        *,
        from_e164: str,
        to_e164: str,
        twiml_url: str,
        status_callback_url: Optional[str] = None,
        timeout_sec: Optional[int] = None,
    ) -> str:
        """Lance un appel sortant via l'API REST Twilio.

        Twilio appelle d'abord `from_e164` (le mobile interne) ; quand
        on décroche, il exécute le TwiML servi par `twiml_url` (typiquement
        un `<Dial>` vers la cible). Retourne le CallSid résultant.
        """
        url = f"{TWILIO_API_BASE}/Accounts/{self.account_sid}/Calls.json"
        form: dict[str, str] = {
            "From": from_e164,
            "To": to_e164,
            "Url": twiml_url,
        }
        if timeout_sec:
            form["Timeout"] = str(int(timeout_sec))
        if status_callback_url:
            form["StatusCallback"] = status_callback_url
            form["StatusCallbackMethod"] = "POST"
            form["StatusCallbackEvent"] = "initiated ringing answered completed"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, data=form, auth=self._auth())
            resp.raise_for_status()
            data = resp.json()
        return str(data.get("sid") or "")

    async def update_call_twiml(self, call_sid: str, twiml_url: str) -> None:
        """Redirige un appel EN COURS vers un nouveau TwiML (interrompt
        le verbe courant — p.ex. sort un appelant de la file d'attente
        pour l'envoyer en boîte vocale)."""
        url = f"{TWILIO_API_BASE}/Accounts/{self.account_sid}/Calls/{call_sid}.json"
        form = {"Url": twiml_url, "Method": "POST"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, data=form, auth=self._auth())
            resp.raise_for_status()

    async def end_call(self, call_sid: str) -> None:
        """Termine un appel (qui sonne ou en cours) — utilisé pour
        raccrocher les jambes parallèles perdantes quand quelqu'un a
        décroché."""
        url = f"{TWILIO_API_BASE}/Accounts/{self.account_sid}/Calls/{call_sid}.json"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                url, data={"Status": "completed"}, auth=self._auth()
            )
            resp.raise_for_status()

    async def start_call_recording(
        self, call_sid: str, *, status_callback_url: Optional[str] = None
    ) -> None:
        """Démarre l'enregistrement (2 pistes) d'un appel en cours —
        utilisé quand le pont passe par une file d'attente (<Enqueue>
        n'a pas d'attribut record). Consentement annoncé par Léa avant."""
        url = (
            f"{TWILIO_API_BASE}/Accounts/{self.account_sid}"
            f"/Calls/{call_sid}/Recordings.json"
        )
        form: dict[str, str] = {"RecordingChannels": "dual"}
        if status_callback_url:
            form["RecordingStatusCallback"] = status_callback_url
            form["RecordingStatusCallbackMethod"] = "POST"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, data=form, auth=self._auth())
            resp.raise_for_status()

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
        action_url: Optional[str] = None,
    ) -> str:
        # `answerOnBridge` : l'appelant entend la sonnerie (pas un "answer"
        # prématuré) jusqu'au vrai pont. Combiné à un `timeout` court, ça
        # permet de REPRENDRE LA MAIN avant que la messagerie du cellulaire
        # cible ne décroche, puis de router vers `action_url` (boîte vocale
        # de l'app) en cas de non-réponse — sinon le message se perd sur la
        # messagerie perso du destinataire.
        attrs = f' timeout="{int(timeout_sec)}" answerOnBridge="true"'
        if caller_id:
            attrs += f' callerId="{xml_escape(caller_id, {chr(34): "&quot;"})}"'
        if action_url:
            attrs += f' action="{xml_escape(action_url)}" method="POST"'
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

        Mapping AWS Polly Neural :
          - fr-CA → Polly.Gabrielle-Neural (français québécois, féminin)
          - fr-FR → Polly.Léa-Neural       (français de France, féminin)
          - en-US → Polly.Joanna-Neural    (anglais américain, féminin)

        ⚠ Important : la voix DOIT matcher la langue. Twilio rejette le
        TwiML avec « application error » si on combine par exemple
        Polly.Léa-Neural (fr-FR) avec language=« fr-CA ». C'est le bug
        qui produisait le message d'erreur Twilio dans nos premiers
        tests d'appels (réf. : AWS Polly voice catalog).
        """
        if lang.startswith("en"):
            return "Polly.Joanna-Neural"
        if lang == "fr-FR":
            return "Polly.Léa-Neural"
        # Défaut français = québécois (Horizon = Montréal).
        return "Polly.Gabrielle-Neural"

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
        whisper_url: Optional[str] = None,
        action_url: Optional[str] = None,
    ) -> str:
        """TwiML : la secrétaire annonce le transfert puis <Dial>.

        Si `whisper_url` est fourni, la personne qui décroche entend
        d'abord le résumé « qui appelle + motif » avant la mise en
        relation. Si `action_url` est fourni, Twilio le POST en cas de
        non-réponse/occupé (fallback, p.ex. boîte vocale)."""
        voice = self._voice_for_lang(lang)
        num_attr = f' url="{xml_escape(whisper_url)}"' if whisper_url else ""
        dial_attr = (
            f' action="{xml_escape(action_url)}" method="POST"'
            if action_url
            else ""
        )
        inner = (
            f"<Number{num_attr}>{xml_escape(dial_to_e164)}</Number>"
            if whisper_url
            else xml_escape(dial_to_e164)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Say voice="{voice}" language="{lang}">{xml_escape(say)}</Say>'
            f'<Dial timeout="{int(timeout_sec)}"{dial_attr}>{inner}</Dial>'
            "</Response>"
        )

    def build_say_and_dial_multi(
        self,
        *,
        say: str,
        lang: str,
        targets_e164: list[str],
        action_url: str,
        timeout_sec: int = 20,
        record: bool = False,
        whisper_url: Optional[str] = None,
    ) -> str:
        """TwiML : la secrétaire annonce le transfert puis <Dial> ring
        PLUSIEURS numéros en parallèle (premier qui décroche gagne, les
        autres s'arrêtent). Si timeout/no-answer/busy, Twilio POST sur
        `action_url` qui sert un TwiML de fallback (callback + notif).

        Si `record=True`, on enregistre l'appel (record-from-answer-dual,
        2 pistes) avec annonce de consentement parlée par Léa AVANT le
        transfert. Loi 25 du Québec exige le consentement explicite.

        Si `whisper_url` est fourni, la personne qui décroche entend
        d'abord ce TwiML (résumé « qui appelle + motif ») avant d'être
        mise en relation — l'appelant, lui, n'entend pas le whisper.
        """
        voice = self._voice_for_lang(lang)
        num_attr = f' url="{xml_escape(whisper_url)}"' if whisper_url else ""
        numbers_xml = "".join(
            f"<Number{num_attr}>{xml_escape(t)}</Number>"
            for t in targets_e164
            if t
        )
        if not numbers_xml:
            # Aucune cible — on ne déclenche pas un <Dial> vide, on
            # bascule directement au fallback.
            return (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<Response>"
                f'<Redirect method="POST">{xml_escape(action_url)}</Redirect>'
                "</Response>"
            )
        record_attr = (
            ' record="record-from-answer-dual" recordingStatusCallbackMethod="POST"'
            if record
            else ""
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Say voice="{voice}" language="{lang}">{xml_escape(say)}</Say>'
            f'<Dial timeout="{int(timeout_sec)}"'
            f' action="{xml_escape(action_url)}" method="POST"{record_attr}>'
            f"{numbers_xml}"
            "</Dial>"
            "</Response>"
        )

    def build_say_and_enqueue(
        self,
        *,
        say: str,
        lang: str,
        queue_name: str,
        action_url: str,
    ) -> str:
        """TwiML côté APPELANT : Léa annonce le transfert, puis l'appelant
        entre dans une file d'attente Twilio. Sans `waitUrl`, Twilio joue
        sa musique d'attente par défaut — c'est ce qu'on veut (au lieu de
        la sonnerie d'un <Dial>). Les agents sont sonnés en parallèle par
        API REST et le premier qui décroche « pioche » l'appelant via
        <Dial><Queue>. `action_url` est appelé quand l'appelant quitte la
        file (bridgé, raccroché, erreur)."""
        voice = self._voice_for_lang(lang)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Say voice="{voice}" language="{lang}">{xml_escape(say)}</Say>'
            f'<Enqueue action="{xml_escape(action_url)}" method="POST">'
            f"{xml_escape(queue_name)}</Enqueue>"
            "</Response>"
        )

    def build_whisper_and_dial_queue(
        self,
        *,
        whisper_say: str,
        lang: str,
        queue_name: str,
    ) -> str:
        """TwiML côté AGENT (jambe sortante REST) : la personne qui
        décroche entend le whisper « qui appelle + motif », puis est mise
        en relation avec l'appelant qui patiente dans la file.

        Le <Say> final se joue dans DEUX cas : file vide (l'appelant a
        raccroché avant la mise en relation) ET fin normale de la
        conversation (l'appelant raccroche le premier) — le message doit
        donc rester neutre pour les deux."""
        voice = self._voice_for_lang(lang)
        gone = (
            "La communication est terminée. Merci !"
            if lang.startswith("fr")
            else "The call has ended. Thank you!"
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Say voice="{voice}" language="{lang}">{xml_escape(whisper_say)}</Say>'
            f"<Dial><Queue>{xml_escape(queue_name)}</Queue></Dial>"
            f'<Say voice="{voice}" language="{lang}">{xml_escape(gone)}</Say>'
            "</Response>"
        )

    def build_say_only(self, *, say: str, lang: str = "fr-CA") -> str:
        """TwiML minimal : une annonce vocale, SANS raccrocher. Utilisé
        comme « whisper » sur un <Number url> : la personne qui décroche
        entend l'annonce, puis Twilio la met automatiquement en relation
        avec l'appelant (qui, lui, n'entend pas le whisper)."""
        voice = self._voice_for_lang(lang)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Say voice="{voice}" language="{lang}">{xml_escape(say)}</Say>'
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

    def build_say_dial_clients_then_mobile(
        self,
        *,
        say: str,
        lang: str,
        clients_xml: str,
        fallback_action_url: str,
        timeout_sec: int = 15,
    ) -> str:
        """TwiML : Léa annonce le transfert, puis <Dial> ring tous les
        Twilio Clients en parallèle. Si timeout sans réponse OU décline,
        Twilio appelle `fallback_action_url` qui sert un TwiML
        secondaire (typiquement `<Dial>+1mobile</Dial>`)."""
        voice = self._voice_for_lang(lang)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Say voice="{voice}" language="{lang}">{xml_escape(say)}</Say>'
            f'<Dial timeout="{int(timeout_sec)}" '
            f'action="{xml_escape(fallback_action_url)}" method="POST">'
            f"{clients_xml}"
            "</Dial>"
            "</Response>"
        )

    def build_voicemail(
        self,
        *,
        intro_say: str,
        lang: str,
        action_url: str,
        transcribe_callback_url: str,
        max_length_sec: int = 90,
    ) -> str:
        """TwiML voicemail (Phase 3) : annonce + enregistrement + transcription.

        Twilio transcrit le message une fois l'enregistrement terminé
        (~5-15 sec selon longueur) et POST le résultat sur
        `transcribe_callback_url`. Les frais de transcription Twilio
        sont minimes (~0.05 $/min de message).
        """
        voice = self._voice_for_lang(lang)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Say voice="{voice}" language="{lang}">{xml_escape(intro_say)}</Say>'
            f'<Record maxLength="{int(max_length_sec)}" '
            f'finishOnKey="#" playBeep="true" '
            f'transcribe="true" '
            f'transcribeCallback="{xml_escape(transcribe_callback_url)}" '
            f'action="{xml_escape(action_url)}" method="POST"/>'
            "</Response>"
        )


_GOODBYE = {
    "fr-CA": "Désolée, je n'ai rien entendu. Bonne journée.",
    "en-US": "Sorry, I didn't catch that. Have a good day.",
}
