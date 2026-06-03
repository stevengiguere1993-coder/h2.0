"""Transcription + résumé IA de l'enregistrement d'un appel humain.

Pipeline : `recording_url` (Twilio) → téléchargement de l'audio →
transcription via Groq Whisper → résumé via le helper IA → stockage sur
le `Call` (`recording_transcription` + `recording_summary`).

Best-effort : tout échec est loggé et levé sous forme de `CallSummaryError`
côté endpoint manuel, mais ne doit jamais casser le flux d'appel quand il
est déclenché en arrière-plan.
"""

from __future__ import annotations

import logging
import os

import httpx

from app.core.config import settings
from app.models.voice import Call

log = logging.getLogger(__name__)

_GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


class CallSummaryError(Exception):
    pass


async def _download_recording(recording_url: str) -> bytes:
    sid = os.getenv("TWILIO_ACCOUNT_SID") or ""
    tok = os.getenv("TWILIO_AUTH_TOKEN") or ""
    url = recording_url
    if not url.endswith((".mp3", ".wav")):
        url = url + ".mp3"
    auth = (sid, tok) if sid and tok else None
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, auth=auth)
        resp.raise_for_status()
        return resp.content


async def _transcribe_groq(audio: bytes) -> str:
    key = (getattr(settings, "groq_api_key", None) or "").strip()
    if not key:
        raise CallSummaryError(
            "Transcription indisponible : GROQ_API_KEY non configurée."
        )
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            _GROQ_WHISPER_URL,
            headers={"Authorization": f"Bearer {key}"},
            files={"file": ("call.mp3", audio, "audio/mpeg")},
            data={
                "model": "whisper-large-v3",
                "language": "fr",
                "response_format": "json",
            },
        )
        resp.raise_for_status()
        return (resp.json().get("text") or "").strip()


async def _summarize(transcript: str) -> str | None:
    try:
        from app.integrations.ai import Message, chat

        res = await chat(
            messages=[
                Message(
                    role="user",
                    content=(
                        "Résume cet appel téléphonique pour le CRM "
                        "d'Horizon Services Immobiliers en 2 à 4 phrases : "
                        "interlocuteur, sujet, décisions/engagements, et "
                        "prochaine action s'il y en a une.\n\n"
                        + transcript[:8000]
                    ),
                )
            ],
            system=(
                "Tu résumes des appels téléphoniques pour un CRM. Réponds "
                "en français québécois, bref et factuel, sans markdown."
            ),
            max_tokens=300,
            temperature=0.3,
        )
        return res.text.strip() or None
    except Exception as exc:  # noqa: BLE001
        log.warning("Résumé d'appel (IA) échoué : %s", exc)
        return None


async def summarize_call_recording(db, call: Call, *, force: bool = False) -> Call:
    """Transcrit + résume l'enregistrement du `call`. `force` régénère
    même si un résumé existe déjà. Lève `CallSummaryError` si pas
    d'enregistrement ou transcription impossible."""
    if not force and call.recording_summary:
        return call
    if not call.recording_url:
        raise CallSummaryError("Aucun enregistrement pour cet appel.")

    audio = await _download_recording(call.recording_url)
    transcript = await _transcribe_groq(audio)
    call.recording_transcription = transcript or None
    call.recording_summary = await _summarize(transcript) if transcript else None
    await db.flush()
    return call


async def summarize_call_in_background(call_id: int) -> None:
    """Tâche fire-and-forget : ouvre sa propre session, résume l'appel.
    Jamais d'exception propagée (best-effort)."""
    try:
        import asyncio

        from sqlalchemy import select

        from app.db.session import AsyncSessionLocal

        # Laisse la requête webhook committer recording_url avant de lire.
        await asyncio.sleep(3)

        async with AsyncSessionLocal() as db:
            call = (
                await db.execute(select(Call).where(Call.id == call_id))
            ).scalar_one_or_none()
            if call is None or not call.recording_url or call.recording_summary:
                return
            await summarize_call_recording(db, call)
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("Résumé d'appel en arrière-plan échoué (id=%s): %s", call_id, exc)
