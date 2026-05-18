"""Bootstrap Twilio : enregistre notre numéro + configure le webhook URL.

Idempotent. À lancer manuellement après le premier déploiement (ou
relancer si on change d'URL backend / si on rajoute un numéro).

    python -m app.scripts.twilio_bootstrap

Lit les env vars suivantes :

    TWILIO_ACCOUNT_SID     (obligatoire)
    TWILIO_AUTH_TOKEN      (obligatoire)
    TWILIO_PHONE_NUMBER    (obligatoire, format E.164 ex. +14388002979)
    TWILIO_FORWARD_TO      (optionnel — mobile à qui forwarder)
    VOICE_WEBHOOK_BASE_URL (optionnel — défaut https://h2-0.onrender.com)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.integrations.voice import get_voice_provider
from app.models.voice import PhoneNumber

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("twilio_bootstrap")


async def main() -> int:
    e164 = (os.getenv("TWILIO_PHONE_NUMBER") or "").strip()
    if not e164:
        log.error("TWILIO_PHONE_NUMBER manquant")
        return 2

    base_url = (os.getenv("VOICE_WEBHOOK_BASE_URL") or "https://h2-0.onrender.com").rstrip("/")
    voice_url = f"{base_url}/api/v1/voice/twilio/voice"
    status_url = f"{base_url}/api/v1/voice/twilio/status"

    try:
        provider = get_voice_provider()
    except RuntimeError as exc:
        log.error("Provider Twilio non configuré : %s", exc)
        return 2

    log.info("Recherche du numéro %s sur Twilio…", e164)
    sid = await provider.find_number_sid(e164)
    if not sid:
        log.error(
            "Le numéro %s ne figure pas dans tes IncomingPhoneNumbers Twilio. "
            "Achète-le d'abord depuis la console.",
            e164,
        )
        return 1
    log.info("→ trouvé : %s", sid)

    log.info("Configuration des webhooks vers %s", base_url)
    await provider.configure_number_webhook(
        provider_sid=sid,
        voice_url=voice_url,
        status_callback_url=status_url,
    )

    # Upsert dans la table voice_phone_numbers.
    forward_to = (os.getenv("TWILIO_FORWARD_TO") or "").strip() or None
    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(select(PhoneNumber).where(PhoneNumber.e164 == e164))
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                PhoneNumber(
                    e164=e164,
                    provider="twilio",
                    provider_sid=sid,
                    label="Ligne principale",
                    forward_to_e164=forward_to,
                    active=True,
                )
            )
            log.info("PhoneNumber créé en base.")
        else:
            existing.provider_sid = sid
            if forward_to and not existing.forward_to_e164:
                existing.forward_to_e164 = forward_to
            existing.active = True
            log.info("PhoneNumber mis à jour en base.")
        await db.commit()

    log.info("✓ Bootstrap terminé. Twilio appellera %s sur le prochain appel entrant.", voice_url)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
