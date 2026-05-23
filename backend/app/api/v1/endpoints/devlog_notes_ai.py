"""IA — Résumé des notes de rencontre prospect (pôle Dev logiciel).

Endpoint dédié, isolé du module ``devlog.py`` pour éviter les conflits
de merge avec les autres chantiers en cours sur le router des leads.

Le résumé est généré via la couche providers-agnostique
``app.integrations.ai`` (Gemini par défaut). Aucun stockage du résumé
côté serveur — le frontend l'affiche en lecture seule et peut le
copier ; les notes brutes restent dans ``DevlogLead.meeting_notes``.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.integrations.ai import (
    AIProviderError,
    AIProviderUnavailable,
    complete,
)
from app.models.devlog_lead import DevlogLead


log = logging.getLogger(__name__)

router = APIRouter(prefix="/devlog/leads", tags=["devlog"])


_SUMMARY_SYSTEM_PROMPT = (
    "Tu es un assistant qui resume des notes de rencontre client en "
    "francais. Le ton est direct, concret, sans bullshit. Structure "
    "obligatoire en quatre sections : 'Contexte', 'Besoins', "
    "'Objections', 'Prochaines etapes'. Maximum 200 mots au total. "
    "Si une section n'a pas d'info dans les notes, ecris 'Aucune "
    "information' sous celle-ci. N'invente jamais de details."
)

_MAX_NOTES_CHARS = 30_000


class SummarizeNotesRequest(BaseModel):
    notes: str = Field(..., min_length=1)


class SummarizeNotesResponse(BaseModel):
    summary: str


@router.post(
    "/{lead_id}/summarize-notes",
    response_model=SummarizeNotesResponse,
)
async def summarize_meeting_notes(
    lead_id: int,
    data: SummarizeNotesRequest,
    db: DBSession,
    user: CurrentUser,  # noqa: ARG001 — auth seulement
) -> SummarizeNotesResponse:
    """Résume des notes de rencontre via Gemini.

    Le lead doit exister (sinon 404). Les notes envoyees dans le body
    ne sont PAS persistees ici — la sauvegarde se fait via PATCH sur
    /devlog/leads/{id} (champ meeting_notes). On accepte le texte en
    parametre pour permettre le resume « live » sans attendre le
    debounce de la sauvegarde frontend.
    """
    notes_text = (data.notes or "").strip()
    if not notes_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Notes vides — rien a resumer.",
        )
    if len(notes_text) > _MAX_NOTES_CHARS:
        notes_text = notes_text[:_MAX_NOTES_CHARS]

    stmt = select(DevlogLead).where(DevlogLead.id == lead_id)
    res = await db.execute(stmt)
    lead: Optional[DevlogLead] = res.scalar_one_or_none()
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead introuvable",
        )

    prompt = (
        "Voici les notes brutes de la rencontre avec le prospect "
        f"« {lead.name} ». Resume-les selon le format demande.\n\n"
        "--- DEBUT DES NOTES ---\n"
        f"{notes_text}\n"
        "--- FIN DES NOTES ---"
    )

    try:
        result = await complete(
            prompt=prompt,
            system=_SUMMARY_SYSTEM_PROMPT,
            max_tokens=600,
            temperature=0.3,
        )
    except AIProviderUnavailable as exc:
        log.warning("summarize-notes : provider IA indisponible : %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Service IA non configure (GEMINI_API_KEY manquante). "
                "Le resume automatique est indisponible."
            ),
        ) from exc
    except AIProviderError as exc:
        log.exception("summarize-notes : erreur provider : %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Resume IA echoue : {exc}",
        ) from exc

    summary = (result.text or "").strip()
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Resume IA vide — reessaie.",
        )
    return SummarizeNotesResponse(summary=summary)
