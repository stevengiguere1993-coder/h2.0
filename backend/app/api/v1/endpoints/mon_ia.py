"""« Mon IA » — connexion IA personnelle par utilisateur.

Chacun branche SA clé API (Anthropic / OpenAI / Google) : les
fonctions IA déclenchées par lui passent par sa clé, et un brief
quotidien donne à son IA la vision de Kratos (filtrée par ses
permissions). La clé n'est JAMAIS renvoyée en clair.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DBSession
from app.integrations.ai._base import AIProviderError
from app.models.user_ai import UserAiConfig
from app.services.user_ai import (
    PROVIDERS_PERSO,
    construire_brief,
    dernier_brief,
    get_config,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/mon-ia", tags=["mon-ia"])


def _masque(cle: str) -> str:
    cle = (cle or "").strip()
    if len(cle) <= 8:
        return "•" * len(cle)
    return f"{cle[:5]}…{cle[-4:]}"


class MonIaRead(BaseModel):
    connecte: bool
    provider: Optional[str] = None
    api_key_masquee: Optional[str] = None
    model: Optional[str] = None
    actif: bool = True
    brief_actif: bool = True
    last_test_ok: Optional[bool] = None
    last_test_at: Optional[datetime] = None
    brief_jour: Optional[date] = None
    brief_contenu: Optional[str] = None


class MonIaWrite(BaseModel):
    provider: str = Field(pattern=r"^(anthropic|openai|gemini)$")
    #: Vide = garder la clé déjà enregistrée (édition du reste).
    api_key: Optional[str] = Field(default=None, max_length=500)
    model: Optional[str] = Field(default=None, max_length=120)
    actif: bool = True
    brief_actif: bool = True


async def _to_read(db, user_id: int, cfg: Optional[UserAiConfig]) -> MonIaRead:
    if cfg is None:
        return MonIaRead(connecte=False)
    brief = await dernier_brief(db, user_id)
    return MonIaRead(
        connecte=True,
        provider=cfg.provider,
        api_key_masquee=_masque(cfg.api_key),
        model=cfg.model,
        actif=cfg.actif,
        brief_actif=cfg.brief_actif,
        last_test_ok=cfg.last_test_ok,
        last_test_at=cfg.last_test_at,
        brief_jour=brief.jour if brief else None,
        brief_contenu=brief.contenu if brief else None,
    )


@router.get("", response_model=MonIaRead)
async def lire(db: DBSession, user: CurrentUser) -> MonIaRead:
    return await _to_read(db, user.id, await get_config(db, user.id))


@router.put("", response_model=MonIaRead)
async def enregistrer(
    payload: MonIaWrite, db: DBSession, user: CurrentUser
) -> MonIaRead:
    cfg = await get_config(db, user.id)
    cle = (payload.api_key or "").strip()
    if cfg is None:
        if not cle:
            raise HTTPException(422, "Fournis ta clé API.")
        cfg = UserAiConfig(
            user_id=user.id,
            provider=payload.provider,
            api_key=cle,
        )
        db.add(cfg)
    else:
        cfg.provider = payload.provider
        if cle:
            cfg.api_key = cle
    cfg.model = (payload.model or "").strip() or None
    cfg.actif = payload.actif
    cfg.brief_actif = payload.brief_actif
    # Un changement de connexion invalide le dernier test.
    if cle:
        cfg.last_test_ok = None
        cfg.last_test_at = None
    await db.commit()
    return await _to_read(db, user.id, cfg)


@router.delete("", status_code=204)
async def deconnecter(db: DBSession, user: CurrentUser) -> None:
    cfg = await get_config(db, user.id)
    if cfg is not None:
        await db.delete(cfg)
        await db.commit()


class TestResult(BaseModel):
    ok: bool
    provider: Optional[str] = None
    model: Optional[str] = None
    reponse: Optional[str] = None
    erreur: Optional[str] = None


@router.post("/test", response_model=TestResult)
async def tester(db: DBSession, user: CurrentUser) -> TestResult:
    cfg = await get_config(db, user.id)
    if cfg is None:
        raise HTTPException(404, "Aucune IA connectée.")
    cls = PROVIDERS_PERSO.get(cfg.provider)
    if cls is None:
        raise HTTPException(422, "Fournisseur inconnu.")
    prov = cls(api_key=cfg.api_key)
    try:
        res = await prov.complete(
            prompt=(
                "Réponds en une courte phrase : tu es bien connecté à "
                f"Kratos pour {user.first_name or user.email}."
            ),
            max_tokens=60,
            temperature=0.2,
            model=(cfg.model or None),
        )
        cfg.last_test_ok = True
        cfg.last_test_at = datetime.now(timezone.utc)
        await db.commit()
        return TestResult(
            ok=True, provider=res.provider, model=res.model,
            reponse=res.text[:300],
        )
    except AIProviderError as exc:
        cfg.last_test_ok = False
        cfg.last_test_at = datetime.now(timezone.utc)
        await db.commit()
        return TestResult(ok=False, erreur=str(exc)[:300])


class BriefResult(BaseModel):
    jour: date
    contenu: str
    provider: Optional[str] = None
    model: Optional[str] = None


@router.post("/brief", response_model=BriefResult)
async def generer_brief(db: DBSession, user: CurrentUser) -> BriefResult:
    """Génère le brief du jour MAINTENANT (sans attendre le cron)."""
    try:
        brief = await construire_brief(db, user)
    except AIProviderError as exc:
        raise HTTPException(502, f"Ton IA a refusé l'appel : {exc}")
    if brief is None:
        raise HTTPException(404, "Aucune IA connectée.")
    await db.commit()
    return BriefResult(
        jour=brief.jour,
        contenu=brief.contenu,
        provider=brief.provider,
        model=brief.model,
    )
