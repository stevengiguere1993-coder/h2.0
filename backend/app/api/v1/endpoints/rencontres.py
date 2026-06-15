"""Endpoints Rencontres (conseil d'actionnaires / retraite stratégique).

  GET    /api/v1/rencontres                       liste paginée
  POST   /api/v1/rencontres                       crée une rencontre
  GET    /api/v1/rencontres/{id}                  détail + sections
  PATCH  /api/v1/rencontres/{id}                  édite
  DELETE /api/v1/rencontres/{id}                  supprime (cascade)
  POST   /api/v1/rencontres/{id}/sections         ajoute une section
  PATCH  /api/v1/rencontres/{id}/sections/{sid}   édite section
  DELETE /api/v1/rencontres/{id}/sections/{sid}   supprime section
  POST   /api/v1/rencontres/{id}/sections/{sid}/summarize
                                                  IA résume section
  POST   /api/v1/rencontres/{id}/sections/{sid}/transcribe
                                                  upload audio → texte
  POST   /api/v1/rencontres/{id}/summarize        résumé global
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import List, Optional

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.rencontre import (
    Rencontre,
    RencontreSection,
    RencontreStatus,
)
from app.services.rencontre_ai import (
    clean_transcript,
    summarize_global,
    summarize_section,
    transcribe_audio,
)


log = logging.getLogger(__name__)
router = APIRouter(prefix="/rencontres", tags=["rencontres"])


_MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB (limite Whisper API OpenAI)


# ── Schémas ──────────────────────────────────────────────────────


class SectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rencontre_id: int
    position: int
    title: str
    transcript: Optional[str]
    ai_summary_json: Optional[str]
    created_at: datetime
    updated_at: datetime


class RencontreListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    meeting_date: Optional[date]
    location: Optional[str]
    entreprise_ids_json: Optional[str]
    status: str
    created_at: datetime
    sections_count: int = 0


class RencontreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    meeting_date: Optional[date]
    location: Optional[str]
    attendees: Optional[str]
    entreprise_ids_json: Optional[str]
    notes: Optional[str]
    global_summary: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime
    sections: List[SectionRead] = Field(default_factory=list)


class RencontreCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    meeting_date: Optional[date] = None
    location: Optional[str] = Field(default=None, max_length=255)
    attendees: Optional[str] = None
    entreprise_ids: Optional[List[int]] = None
    notes: Optional[str] = None


class RencontreUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    meeting_date: Optional[date] = None
    location: Optional[str] = Field(default=None, max_length=255)
    attendees: Optional[str] = None
    entreprise_ids: Optional[List[int]] = None
    notes: Optional[str] = None
    global_summary: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern=r"^(draft|done)$")


class SectionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    transcript: Optional[str] = None
    position: Optional[int] = None


class SectionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    transcript: Optional[str] = None
    position: Optional[int] = None


# ── Helpers ──────────────────────────────────────────────────────


def _serialize_ids(ids: Optional[List[int]]) -> Optional[str]:
    if not ids:
        return None
    return json.dumps([int(x) for x in ids])


async def _get_rencontre_or_404(db, rencontre_id: int) -> Rencontre:
    row = (
        await db.execute(
            select(Rencontre).where(Rencontre.id == rencontre_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Rencontre introuvable."
        )
    return row


async def _get_section_or_404(
    db, rencontre_id: int, section_id: int
) -> RencontreSection:
    row = (
        await db.execute(
            select(RencontreSection).where(
                RencontreSection.id == section_id,
                RencontreSection.rencontre_id == rencontre_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Section introuvable."
        )
    return row


# ── Endpoints rencontres ─────────────────────────────────────────


@router.get(
    "",
    response_model=List[RencontreListItem],
    summary="Liste les rencontres (filtre optionnel par entreprise)",
)
async def list_rencontres(
    db: DBSession,
    _: CurrentUser,
    entreprise_id: Optional[int] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
) -> List[RencontreListItem]:
    rows = (
        await db.execute(
            select(Rencontre)
            .order_by(Rencontre.meeting_date.desc().nulls_last(), Rencontre.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    out: List[RencontreListItem] = []
    for r in rows:
        ent_ids = []
        if r.entreprise_ids_json:
            try:
                ent_ids = json.loads(r.entreprise_ids_json) or []
            except Exception:  # noqa: BLE001
                pass
        if entreprise_id is not None and entreprise_id not in ent_ids:
            continue
        sc = (
            await db.execute(
                select(RencontreSection).where(
                    RencontreSection.rencontre_id == r.id
                )
            )
        ).scalars().all()
        item = RencontreListItem.model_validate(r)
        item.sections_count = len(sc)
        out.append(item)
    return out


@router.post(
    "",
    response_model=RencontreRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_rencontre(
    data: RencontreCreate,
    db: DBSession,
    user: CurrentUser,
) -> RencontreRead:
    r = Rencontre(
        title=data.title.strip(),
        meeting_date=data.meeting_date,
        location=data.location,
        attendees=data.attendees,
        entreprise_ids_json=_serialize_ids(data.entreprise_ids),
        notes=data.notes,
        created_by_user_id=user.id,
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)

    # Section par défaut : on évite à l'utilisateur l'étape « ajouter un
    # topic ». Le sujet est déjà le nom de la rencontre — on crée donc une
    # section prête à recevoir audio / texte / dictée immédiatement.
    db.add(
        RencontreSection(
            rencontre_id=r.id,
            position=0,
            title=r.title,
        )
    )
    await db.commit()
    await db.refresh(r)
    return RencontreRead.model_validate(r)


@router.get("/{rencontre_id}", response_model=RencontreRead)
async def get_rencontre(
    rencontre_id: int, db: DBSession, _: CurrentUser
) -> RencontreRead:
    r = await _get_rencontre_or_404(db, rencontre_id)
    sections = (
        await db.execute(
            select(RencontreSection)
            .where(RencontreSection.rencontre_id == rencontre_id)
            .order_by(RencontreSection.position.asc(), RencontreSection.id.asc())
        )
    ).scalars().all()
    out = RencontreRead.model_validate(r)
    out.sections = [SectionRead.model_validate(s) for s in sections]
    return out


@router.patch("/{rencontre_id}", response_model=RencontreRead)
async def update_rencontre(
    rencontre_id: int,
    data: RencontreUpdate,
    db: DBSession,
    _: CurrentUser,
) -> RencontreRead:
    r = await _get_rencontre_or_404(db, rencontre_id)
    payload = data.model_dump(exclude_unset=True)
    if "entreprise_ids" in payload:
        r.entreprise_ids_json = _serialize_ids(payload.pop("entreprise_ids"))
    for k, v in payload.items():
        setattr(r, k, v)
    await db.commit()
    await db.refresh(r)
    return RencontreRead.model_validate(r)


@router.delete(
    "/{rencontre_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_rencontre(
    rencontre_id: int, db: DBSession, _: CurrentUser
) -> None:
    r = await _get_rencontre_or_404(db, rencontre_id)
    await db.delete(r)
    await db.commit()


# ── Endpoints sections ───────────────────────────────────────────


@router.post(
    "/{rencontre_id}/sections",
    response_model=SectionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_section(
    rencontre_id: int,
    data: SectionCreate,
    db: DBSession,
    _: CurrentUser,
) -> SectionRead:
    await _get_rencontre_or_404(db, rencontre_id)
    # Position auto = max + 1
    existing = (
        await db.execute(
            select(RencontreSection)
            .where(RencontreSection.rencontre_id == rencontre_id)
            .order_by(RencontreSection.position.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    next_pos = (existing.position + 1) if existing else 0
    s = RencontreSection(
        rencontre_id=rencontre_id,
        position=data.position if data.position is not None else next_pos,
        title=data.title.strip(),
        transcript=data.transcript,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return SectionRead.model_validate(s)


@router.patch(
    "/{rencontre_id}/sections/{section_id}",
    response_model=SectionRead,
)
async def update_section(
    rencontre_id: int,
    section_id: int,
    data: SectionUpdate,
    db: DBSession,
    _: CurrentUser,
) -> SectionRead:
    s = await _get_section_or_404(db, rencontre_id, section_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    await db.commit()
    await db.refresh(s)
    return SectionRead.model_validate(s)


@router.delete(
    "/{rencontre_id}/sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_section(
    rencontre_id: int,
    section_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    s = await _get_section_or_404(db, rencontre_id, section_id)
    await db.delete(s)
    await db.commit()


# ── IA : résumé section + global, transcription audio ────────────


@router.post(
    "/{rencontre_id}/sections/{section_id}/summarize",
    response_model=SectionRead,
    summary="Génère le résumé IA structuré d'une section",
)
async def summarize_section_endpoint(
    rencontre_id: int,
    section_id: int,
    db: DBSession,
    _: CurrentUser,
) -> SectionRead:
    s = await _get_section_or_404(db, rencontre_id, section_id)
    # Charge les entreprises de la rencontre pour donner du contexte
    # à Claude → tagging précis des action_items par entreprise.
    r = await _get_rencontre_or_404(db, rencontre_id)
    ent_ids: list[int] = []
    if r.entreprise_ids_json:
        try:
            v = json.loads(r.entreprise_ids_json)
            if isinstance(v, list):
                ent_ids = [int(x) for x in v if isinstance(x, (int, str))]
        except Exception:  # noqa: BLE001
            ent_ids = []
    entreprises_context: list[dict] = []
    if ent_ids:
        from app.models.entreprise import Entreprise as _Ent

        rows = (
            await db.execute(
                select(_Ent).where(_Ent.id.in_(ent_ids))
            )
        ).scalars().all()
        entreprises_context = [
            {"id": e.id, "name": e.name} for e in rows
        ]
    summary = await summarize_section(
        s.title, s.transcript or "", entreprises_context=entreprises_context
    )
    s.ai_summary_json = json.dumps(summary, default=str)[:20_000]
    await db.commit()
    await db.refresh(s)
    return SectionRead.model_validate(s)


@router.post(
    "/{rencontre_id}/summarize",
    response_model=RencontreRead,
    summary="Génère le résumé global de la rencontre",
)
async def summarize_global_endpoint(
    rencontre_id: int,
    db: DBSession,
    _: CurrentUser,
) -> RencontreRead:
    r = await _get_rencontre_or_404(db, rencontre_id)
    sections = (
        await db.execute(
            select(RencontreSection)
            .where(RencontreSection.rencontre_id == rencontre_id)
            .order_by(RencontreSection.position.asc())
        )
    ).scalars().all()
    sections_dicts: list[dict] = []
    for s in sections:
        d = {"title": s.title, "summary": "", "decisions": [], "action_items": [], "open_questions": [], "risks": []}
        if s.ai_summary_json:
            try:
                d.update(json.loads(s.ai_summary_json))
                d["title"] = s.title  # toujours forcer
            except Exception:  # noqa: BLE001
                pass
        sections_dicts.append(d)
    global_text = await summarize_global(sections_dicts)
    r.global_summary = global_text[:20_000]
    r.status = RencontreStatus.DONE.value
    await db.commit()
    await db.refresh(r)
    out = RencontreRead.model_validate(r)
    out.sections = [SectionRead.model_validate(s) for s in sections]
    return out


@router.post(
    "/{rencontre_id}/sections/{section_id}/clean-transcript",
    response_model=SectionRead,
    summary=(
        "Réécrit le transcript brut de la dictée en français québécois "
        "propre (homophones, accents, ponctuation, mots mal entendus)."
    ),
)
async def clean_transcript_endpoint(
    rencontre_id: int,
    section_id: int,
    db: DBSession,
    _: CurrentUser,
) -> SectionRead:
    s = await _get_section_or_404(db, rencontre_id, section_id)
    # Contexte entreprises (mêmes infos que pour le summarize) pour que
    # Claude corrige les noms propres mal transcrits.
    r = await _get_rencontre_or_404(db, rencontre_id)
    ent_ids: list[int] = []
    if r.entreprise_ids_json:
        try:
            v = json.loads(r.entreprise_ids_json)
            if isinstance(v, list):
                ent_ids = [int(x) for x in v if isinstance(x, (int, str))]
        except Exception:  # noqa: BLE001
            ent_ids = []
    entreprises_context: list[dict] = []
    if ent_ids:
        from app.models.entreprise import Entreprise as _Ent

        rows = (
            await db.execute(select(_Ent).where(_Ent.id.in_(ent_ids)))
        ).scalars().all()
        entreprises_context = [
            {"id": e.id, "name": e.name} for e in rows
        ]
    cleaned = await clean_transcript(
        s.transcript or "", entreprises_context=entreprises_context
    )
    s.transcript = cleaned
    await db.commit()
    await db.refresh(s)
    return SectionRead.model_validate(s)


@router.post(
    "/{rencontre_id}/sections/{section_id}/transcribe",
    response_model=SectionRead,
    summary="Upload un audio → Whisper transcrit → append au transcript",
)
async def transcribe_section(
    rencontre_id: int,
    section_id: int,
    db: DBSession,
    _: CurrentUser,
    file: UploadFile = File(...),
) -> SectionRead:
    s = await _get_section_or_404(db, rencontre_id, section_id)
    data = await file.read()
    if len(data) > _MAX_AUDIO_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Fichier audio > 25 MB (limite Whisper). Découpe-le.",
        )
    try:
        transcript = await transcribe_audio(
            file.filename or "audio", file.content_type or "audio/mpeg", data
        )
    except RuntimeError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)
        ) from exc
    # Append au transcript existant pour ne rien perdre.
    if s.transcript:
        s.transcript = s.transcript + "\n\n" + transcript
    else:
        s.transcript = transcript
    await db.commit()
    await db.refresh(s)
    return SectionRead.model_validate(s)
