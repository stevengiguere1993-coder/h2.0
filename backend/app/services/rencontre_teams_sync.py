"""Synchro Teams → fiches Rencontres.

Scanne les calendriers des organisateurs configurés
(``TEAMS_MEETING_USER_EMAILS``), repère les rencontres Teams terminées,
récupère leur transcription (si activée pendant le meeting) et crée une
fiche Rencontre pré-remplie : transcription en section + résumé
structuré + résumé global — il ne reste qu'à valider.

Idempotent via :class:`TeamsMeetingImport` (clé = iCalUId). Si un
meeting terminé n'a pas (encore) de transcription, on réessaie aux
prochains passages pendant quelques heures (Teams met un peu de temps à
la publier), puis on le marque ``no_transcript`` pour ne plus y revenir.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import ms_graph_meetings as graph
from app.models.rencontre import Rencontre, RencontreSection
from app.models.teams_meeting_import import TeamsMeetingImport
from app.services.audit import log_action
from app.services.rencontre_ai import summarize_global, summarize_section

log = logging.getLogger(__name__)

# Délai après la fin d'un meeting avant d'abandonner la recherche de
# transcription (Teams la publie normalement en quelques minutes).
_GIVE_UP_AFTER = timedelta(hours=6)
# Garde-fou : nombre max de fiches créées par passage (quota IA).
_MAX_IMPORTS_PER_RUN = 10


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def sync_teams_meetings(
    db: AsyncSession, *, days_back: int = 3
) -> dict:
    """Lance une passe de synchro. Retourne un bilan sérialisable."""
    result: dict = {
        "configured": graph.graph_meetings_configured(),
        "imported": [],
        "no_transcript": 0,
        "pending": 0,
        "skipped_known": 0,
        "errors": [],
    }
    if not result["configured"]:
        return result

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days_back)

    # 1) Collecte des meetings terminés, dédoublonnés entre les boîtes
    # (le même daily apparaît dans le calendrier de chaque partenaire).
    meetings: dict[str, dict] = {}
    for email in graph.meeting_user_emails():
        try:
            events = await graph.list_teams_meetings(email, start, now)
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"{email}: {str(exc)[:150]}")
            continue
        for ev in events:
            key = ev.get("ical_uid") or ev.get("join_url") or ""
            if not key:
                continue
            ended = _parse_dt(ev.get("end"))
            if ended is None or ended > now:
                continue  # pas terminé
            ev["_mailbox"] = email
            meetings.setdefault(key, ev)

    if not meetings:
        return result

    # 2) Écarte ceux déjà traités.
    known = {
        row[0]
        for row in (
            await db.execute(
                select(TeamsMeetingImport.ical_uid).where(
                    TeamsMeetingImport.ical_uid.in_(list(meetings.keys()))
                )
            )
        ).all()
    }
    result["skipped_known"] = len(known)

    imported_count = 0
    for key, ev in meetings.items():
        if key in known:
            continue
        if imported_count >= _MAX_IMPORTS_PER_RUN:
            result["pending"] += 1
            continue
        mailbox = ev["_mailbox"]
        try:
            meeting_id = await graph.resolve_online_meeting(
                mailbox, ev["join_url"]
            )
            transcript = (
                await graph.fetch_transcript_text(mailbox, meeting_id)
                if meeting_id
                else None
            )
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(
                f"{ev.get('subject')}: {str(exc)[:150]}"
            )
            continue

        if not transcript:
            ended = _parse_dt(ev.get("end"))
            if ended and (datetime.now(timezone.utc) - ended) > _GIVE_UP_AFTER:
                # Terminé depuis longtemps sans transcription → on classe.
                db.add(
                    TeamsMeetingImport(
                        ical_uid=key,
                        subject=ev.get("subject"),
                        organizer_email=ev.get("organizer_email"),
                        meeting_start=ev.get("start"),
                        status="no_transcript",
                    )
                )
                await db.flush()
                result["no_transcript"] += 1
            else:
                # Transcription peut-être pas encore publiée → retentera.
                result["pending"] += 1
            continue

        # 3) Création de la fiche pré-remplie.
        started = _parse_dt(ev.get("start"))
        rencontre = Rencontre(
            title=ev.get("subject") or "Rencontre Teams",
            meeting_date=started.date() if started else None,
            location="Teams",
            attendees=", ".join(ev.get("attendees") or []) or None,
            notes="Importée automatiquement depuis Teams.",
            status="draft",
        )
        db.add(rencontre)
        await db.flush()

        section = RencontreSection(
            rencontre_id=rencontre.id,
            position=0,
            title="Transcription Teams",
            transcript=transcript,
        )
        db.add(section)
        await db.flush()

        # 4) Résumés IA (best-effort — la fiche reste utile sans).
        try:
            summary = await summarize_section(
                section.title, transcript, None
            )
            section.ai_summary_json = json.dumps(
                summary, ensure_ascii=False
            )
            rencontre.global_summary = await summarize_global(
                [
                    {
                        "title": section.title,
                        **(summary if isinstance(summary, dict) else {}),
                    }
                ]
            )
            rencontre.status = "done"
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Résumé IA échoué pour « %s » : %s",
                rencontre.title,
                exc,
            )

        db.add(
            TeamsMeetingImport(
                ical_uid=key,
                subject=ev.get("subject"),
                organizer_email=ev.get("organizer_email"),
                meeting_start=ev.get("start"),
                status="imported",
                rencontre_id=rencontre.id,
            )
        )
        await db.flush()
        await log_action(
            db,
            user=None,
            action="rencontre.teams_imported",
            entity_type="rencontre",
            entity_id=rencontre.id,
            details={"subject": ev.get("subject"), "mailbox": mailbox},
        )
        result["imported"].append(
            {"rencontre_id": rencontre.id, "title": rencontre.title}
        )
        imported_count += 1

    return result
