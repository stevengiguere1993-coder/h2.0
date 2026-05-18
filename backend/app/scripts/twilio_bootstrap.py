"""Bootstrap Twilio : enregistre notre numéro + configure le webhook URL.

Idempotent. Appelé automatiquement au démarrage de l'app via `lifespan`
quand les credentials Twilio sont présents. Peut aussi être lancé à la
main :

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

log = logging.getLogger("twilio_bootstrap")


async def bootstrap_twilio(force: bool = False) -> int:
    """Configure le numéro Twilio + insère la ligne en DB. Idempotent.

    Args:
        force: si True, reconfigure même si le PhoneNumber est déjà
            enregistré avec un provider_sid. Utile pour pousser une
            nouvelle voice_url après changement de domaine.

    Returns:
        0 si tout est OK / déjà à jour ; 1 si le numéro n'a pas été
        trouvé chez Twilio ; 2 si la configuration env est incomplète.
    """
    raw_env = (os.getenv("TWILIO_PHONE_NUMBER") or "").strip()
    # Normalisation E.164 : si l'utilisateur saisit "14388002979" sans
    # le `+` initial, on l'ajoute. Sinon Twilio renvoie 404 sur le
    # lookup et le bootstrap échoue sans raison apparente.
    if raw_env and not raw_env.startswith("+"):
        digits = "".join(c for c in raw_env if c.isdigit())
        if len(digits) == 10:
            e164 = f"+1{digits}"
        elif len(digits) == 11 and digits.startswith("1"):
            e164 = f"+{digits}"
        else:
            e164 = f"+{digits}" if digits else ""
        log.info(
            "TWILIO_PHONE_NUMBER normalisé : %r → %r (ajoute le « + » à ton env Render quand tu peux)",
            raw_env, e164,
        )
    else:
        e164 = raw_env
    if not e164:
        log.info("TWILIO_PHONE_NUMBER vide — bootstrap Twilio sauté.")
        return 2

    try:
        provider = get_voice_provider()
    except RuntimeError as exc:
        log.info("Provider Twilio non configuré (%s) — bootstrap sauté.", exc)
        return 2

    # Dedupe : si plusieurs lignes PhoneNumber existent pour le même
    # numéro physique (ex. « 14388002979 » sans + créée par un ancien
    # bootstrap + « +14388002979 » créée par self-heal), on les
    # fusionne. Critère : 10 derniers chiffres identiques.
    await _dedupe_phone_numbers(canonical_e164=e164)

    # Fast path : si on a déjà la ligne en base avec un provider_sid,
    # rien à faire (sauf si on force).
    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(select(PhoneNumber).where(PhoneNumber.e164 == e164))
        ).scalar_one_or_none()
        if existing is not None and existing.provider_sid and not force:
            log.info("PhoneNumber %s déjà bootstrapé (sid=%s)", e164, existing.provider_sid)
            return 0

    base_url = (os.getenv("VOICE_WEBHOOK_BASE_URL") or "https://h2-0.onrender.com").rstrip("/")
    voice_url = f"{base_url}/api/v1/voice/twilio/voice"
    status_url = f"{base_url}/api/v1/voice/twilio/status"

    log.info("Recherche du numéro %s sur Twilio…", e164)
    sid = await provider.find_number_sid(e164)
    if not sid:
        log.warning(
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
    # SMS — webhook bidirectionnel sur le même numéro.
    sms_url = f"{base_url}/api/v1/voice/twilio/sms"
    try:
        await provider.configure_number_sms_webhook(
            provider_sid=sid, sms_url=sms_url
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("SMS webhook config failed (non bloquant) : %s", exc)

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

    log.info("✓ Bootstrap terminé. Twilio appellera %s.", voice_url)
    return 0


async def _dedupe_phone_numbers(*, canonical_e164: str) -> int:
    """Fusionne les doublons PhoneNumber qui ont les mêmes 10 derniers
    chiffres mais des formats différents (« 14388002979 » vs
    « +14388002979 »).

    Stratégie :
    - On garde la ligne dont le e164 == canonical_e164 (format E.164
      propre avec « + »). Si elle n'existe pas, on en élit une.
    - On fusionne les toggles (OR sur secretary_mode_active,
      lead_auto_callback_enabled, active).
    - Pour les doublons : on réassigne tous les voice_calls, voice_sms,
      voice_filters, voice_business_hours vers la ligne canonique, puis
      on supprime le doublon.
    """
    from sqlalchemy import func, update

    from app.models.voice import (
        Call,
        VoiceBusinessHours,
        VoiceFilter,
        VoiceSms,
    )

    digits_canonical = "".join(c for c in canonical_e164 if c.isdigit())[-10:]
    if not digits_canonical:
        return 0

    async with AsyncSessionLocal() as db:
        # Cherche TOUTES les lignes dont les 10 derniers chiffres matchent.
        rows = (
            await db.execute(
                select(PhoneNumber).where(
                    func.right(
                        func.regexp_replace(PhoneNumber.e164, r"[^0-9]", "", "g"),
                        10,
                    )
                    == digits_canonical
                )
            )
        ).scalars().all()
        if len(rows) <= 1:
            return 0

        # Élit la canonique : celle dont e164 == canonical_e164 si elle
        # existe, sinon la 1re créée (id le plus bas).
        keep = next((r for r in rows if r.e164 == canonical_e164), None)
        if keep is None:
            keep = min(rows, key=lambda r: r.id)
            keep.e164 = canonical_e164  # rename to canonical
        dups = [r for r in rows if r.id != keep.id]

        log.warning(
            "Dedupe PhoneNumber pour %s : %d doublon(s) trouvé(s), "
            "fusion vers id=%d (e164=%s)",
            canonical_e164, len(dups), keep.id, keep.e164,
        )

        for dup in dups:
            # Merge toggles : OR booléens (si l'un était actif, on garde actif).
            keep.secretary_mode_active = (
                keep.secretary_mode_active or dup.secretary_mode_active
            )
            keep.lead_auto_callback_enabled = (
                keep.lead_auto_callback_enabled or dup.lead_auto_callback_enabled
            )
            keep.active = keep.active or dup.active
            # Préserve forward_to_e164 et provider_sid si keep ne l'a pas.
            if not keep.forward_to_e164 and dup.forward_to_e164:
                keep.forward_to_e164 = dup.forward_to_e164
            if not keep.provider_sid and dup.provider_sid:
                keep.provider_sid = dup.provider_sid
            if not keep.label and dup.label:
                keep.label = dup.label

            # Réassigne les FK des tables enfants.
            for cls in (Call, VoiceSms, VoiceFilter, VoiceBusinessHours):
                await db.execute(
                    update(cls)
                    .where(cls.phone_number_id == dup.id)
                    .values(phone_number_id=keep.id)
                )

            # Supprime le doublon.
            await db.delete(dup)
            log.info("→ Supprimé doublon id=%d e164=%r", dup.id, dup.e164)

        await db.commit()
        return len(dups)


async def _cli_main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # --force pour reconfigurer même si déjà bootstrapé.
    force = "--force" in sys.argv
    return await bootstrap_twilio(force=force)


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli_main()))
