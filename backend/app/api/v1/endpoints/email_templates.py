"""Templates de courriels — CRUD + envoi avec interpolation.

Variables supportées (Mustache-style {{var}}) :
- {{nom}}                 — nom du destinataire
- {{prenom}}              — prénom (split sur le 1er espace)
- {{adresse}}             — adresse de l'immeuble/du chantier
- {{soumission_id}}       — # de soumission (si lié)
- {{prospecteur}}         — nom du commercial qui envoie
- {{horizon_phone}}       — numéro Horizon
- {{horizon_url}}         — URL du site
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.email_template import EmailTemplate

log = logging.getLogger(__name__)

router = APIRouter(prefix="/email-templates", tags=["email-templates"])


# ----------------------------- Schemas -----------------------------


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str]
    subject: str
    body_html: str
    category: str
    created_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = None
    subject: str = Field(min_length=1, max_length=500)
    body_html: str = Field(min_length=1)
    category: str = Field(default="custom", max_length=32)


class TemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    subject: Optional[str] = Field(default=None, min_length=1, max_length=500)
    body_html: Optional[str] = Field(default=None, min_length=1)
    category: Optional[str] = Field(default=None, max_length=32)


class SendIn(BaseModel):
    to: List[EmailStr] = Field(min_length=1, max_length=10)
    cc: Optional[List[EmailStr]] = None
    variables: dict = Field(default_factory=dict)
    # Override le sujet/body si l'utilisateur a édité avant l'envoi.
    subject_override: Optional[str] = None
    body_html_override: Optional[str] = None


class PreviewIn(BaseModel):
    variables: dict = Field(default_factory=dict)


class PreviewOut(BaseModel):
    subject: str
    body_html: str


# ----------------------------- Render helper -----------------------------


_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render_template(text: str, variables: dict) -> str:
    """Remplace tous les `{{var}}` par variables.get(var, ''). Variables
    inconnues sont remplacées par une chaîne vide pour éviter qu'on
    envoie un courriel avec « {{nom}} » dedans."""
    if not text:
        return ""

    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        v = variables.get(key)
        return "" if v is None else str(v)

    return _PLACEHOLDER_RE.sub(_sub, text)


# ----------------------------- Endpoints -----------------------------


@router.get("", response_model=List[TemplateRead])
async def list_templates(
    db: DBSession, _: CurrentUser
) -> List[TemplateRead]:
    rows = (
        await db.execute(
            select(EmailTemplate).order_by(EmailTemplate.name.asc())
        )
    ).scalars().all()
    return [TemplateRead.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=TemplateRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    data: TemplateCreate, db: DBSession, user: RequireManager
) -> TemplateRead:
    t = EmailTemplate(
        name=data.name.strip(),
        description=(data.description or "").strip() or None,
        subject=data.subject.strip(),
        body_html=data.body_html,
        category=data.category,
        created_by_user_id=user.id,
    )
    db.add(t)
    await db.flush()
    await db.refresh(t)
    return TemplateRead.model_validate(t)


@router.get("/{tpl_id}", response_model=TemplateRead)
async def get_template(
    tpl_id: int, db: DBSession, _: CurrentUser
) -> TemplateRead:
    t = (
        await db.execute(
            select(EmailTemplate).where(EmailTemplate.id == tpl_id)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "Template introuvable.")
    return TemplateRead.model_validate(t)


@router.patch("/{tpl_id}", response_model=TemplateRead)
async def update_template(
    tpl_id: int,
    data: TemplateUpdate,
    db: DBSession,
    _: RequireManager,
) -> TemplateRead:
    t = (
        await db.execute(
            select(EmailTemplate).where(EmailTemplate.id == tpl_id)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "Template introuvable.")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    await db.flush()
    await db.refresh(t)
    return TemplateRead.model_validate(t)


@router.delete(
    "/{tpl_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_template(
    tpl_id: int, db: DBSession, _: RequireManager
) -> None:
    res = await db.execute(
        delete(EmailTemplate).where(EmailTemplate.id == tpl_id)
    )
    if (res.rowcount or 0) == 0:
        raise HTTPException(404, "Template introuvable.")


@router.post(
    "/{tpl_id}/preview",
    response_model=PreviewOut,
    summary="Render un template avec les variables fournies — pas "
    "d'envoi, juste pour preview avant envoi.",
)
async def preview_template(
    tpl_id: int,
    data: PreviewIn,
    db: DBSession,
    _: CurrentUser,
) -> PreviewOut:
    t = (
        await db.execute(
            select(EmailTemplate).where(EmailTemplate.id == tpl_id)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "Template introuvable.")
    return PreviewOut(
        subject=render_template(t.subject, data.variables),
        body_html=render_template(t.body_html, data.variables),
    )


@router.post(
    "/{tpl_id}/send",
    summary="Render et envoie le template via Microsoft Graph "
    "(infra existante, pas de coût supplémentaire).",
)
async def send_template(
    tpl_id: int,
    data: SendIn,
    db: DBSession,
    _: CurrentUser,
) -> dict:
    t = (
        await db.execute(
            select(EmailTemplate).where(EmailTemplate.id == tpl_id)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "Template introuvable.")

    subject = (
        data.subject_override
        if data.subject_override is not None
        else render_template(t.subject, data.variables)
    )
    body_html = (
        data.body_html_override
        if data.body_html_override is not None
        else render_template(t.body_html, data.variables)
    )

    try:
        from app.integrations.email_graph import get_mailer

        mailer = get_mailer()
        await mailer.send(
            to=[str(e) for e in data.to],
            subject=subject,
            html_body=body_html,
            cc=[str(e) for e in (data.cc or [])] or None,
        )
    except Exception as exc:
        log.warning("send_template %s failed: %s", tpl_id, exc)
        raise HTTPException(
            502,
            "Envoi du courriel échoué. Vérifie la connexion Microsoft "
            "Graph dans /app/parametres.",
        ) from exc

    return {"sent": True, "subject": subject, "to": [str(e) for e in data.to]}
