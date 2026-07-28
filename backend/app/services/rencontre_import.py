"""Hub Rencontres v2 — import unifié + archivage Drive.

Une seule porte d'entrée (retour Phil 2026-07-28) : un fichier AUDIO
(Samsung Recorder…), un transcript Teams (.vtt), un fichier texte ou un
texte collé → une Rencontre avec transcript prêt à résumer. L'audio et
le transcript sont archivés dans Google Drive (« Rencontres Kratos »)
en best-effort — jamais bloquant.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

#: Extensions texte acceptées telles quelles.
_TEXT_EXTS = {".txt", ".md", ".text"}
_VTT_EXTS = {".vtt", ".srt"}


def parse_vtt(raw: str) -> str:
    """Transcript Teams/WebVTT (ou SRT) → texte lisible « Nom : … ».

    - retire l'entête WEBVTT, les identifiants de cue et les timestamps ;
    - convertit ``<v Prénom Nom>texte</v>`` en « Prénom Nom : texte » ;
    - fusionne les répliques consécutives du même interlocuteur.
    """
    lines_out: list[tuple[Optional[str], str]] = []
    ts = re.compile(r"^\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->")
    for rawline in raw.splitlines():
        line = rawline.strip()
        if not line or line.upper().startswith(("WEBVTT", "NOTE", "STYLE")):
            continue
        if ts.match(line):
            continue
        # Identifiant de cue seul sur sa ligne : numérique (VTT/SRT
        # simple) ou GUID Teams (« 6a05…-cbc7/19-1 »). PAS un mot seul
        # (« Merci ») — on exige chiffres purs ou forme hexa longue.
        if re.fullmatch(r"\d+|[0-9a-fA-F-]{16,}(/[\d-]+)?", line):
            continue
        speaker = None
        m = re.match(r"<v\s+([^>]+)>(.*?)(</v>)?\s*$", line)
        if m:
            speaker = m.group(1).strip()
            text = m.group(2).strip()
        else:
            text = re.sub(r"</?[^>]+>", "", line).strip()
        if not text:
            continue
        if speaker is not None and lines_out and lines_out[-1][0] == speaker:
            prev_speaker, prev_text = lines_out[-1]
            lines_out[-1] = (prev_speaker, f"{prev_text} {text}")
        else:
            lines_out.append((speaker, text))
    parts = []
    for speaker, text in lines_out:
        parts.append(f"{speaker} : {text}" if speaker else text)
    return "\n".join(parts).strip()


def detecter_type(filename: str, content_type: str) -> str:
    """'audio' | 'vtt' | 'texte' — selon l'extension puis le MIME."""
    name = (filename or "").lower()
    for ext in _VTT_EXTS:
        if name.endswith(ext):
            return "vtt"
    for ext in _TEXT_EXTS:
        if name.endswith(ext):
            return "texte"
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime.startswith("audio/") or mime in (
        "video/mp4", "application/octet-stream",
    ):
        # Samsung Recorder partage parfois en octet-stream ; les .m4a
        # sortent aussi en video/mp4 selon l'app.
        return "audio"
    if mime.startswith("text/"):
        return "texte"
    return "audio"


async def archiver_drive(
    db,
    user_id: Optional[int],
    titre: str,
    *,
    audio: Optional[tuple[str, bytes, str]] = None,
    transcript: Optional[str] = None,
) -> Optional[str]:
    """Dépose l'audio original et/ou le transcript (.txt) dans le Drive
    de l'utilisateur, dossier « Rencontres Kratos ». Retourne le JSON
    ``[{"name":…, "link":…}]`` ou None. JAMAIS bloquant."""
    if user_id is None or (audio is None and not transcript):
        return None
    try:
        from app.services.drive_api import upload_file
        from app.services.drive_auto_upload_dispatcher import (
            ensure_subfolder_path,
        )

        folder_id = await ensure_subfolder_path(
            user_id, "root", "Rencontres Kratos", db
        )
        safe = re.sub(r"[\\/:*?\"<>|]+", "-", titre).strip() or "Rencontre"
        links: list[dict] = []
        if audio is not None:
            fname, data, mime = audio
            ext = "." + fname.rsplit(".", 1)[-1] if "." in fname else ".m4a"
            created = await upload_file(
                user_id, db, folder_id, f"{safe}{ext}", data, mime_type=mime
            )
            links.append(
                {
                    "name": created.get("name"),
                    "link": created.get("webViewLink"),
                }
            )
        if transcript:
            created = await upload_file(
                user_id,
                db,
                folder_id,
                f"{safe} — transcript.txt",
                transcript.encode("utf-8"),
                mime_type="text/plain",
            )
            links.append(
                {
                    "name": created.get("name"),
                    "link": created.get("webViewLink"),
                }
            )
        return json.dumps(links) if links else None
    except Exception as exc:  # noqa: BLE001 — best-effort, jamais bloquant
        log.info("Archivage Drive de la rencontre sauté : %s", exc)
        return None
