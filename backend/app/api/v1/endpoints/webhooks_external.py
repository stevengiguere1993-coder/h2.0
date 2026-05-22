"""Webhook générique pour leads venant d'un outil tiers (Zapier, Make…).

Reçoit un POST JSON authentifié par un header partagé
``X-Webhook-Secret``. Crée une ``ContactRequest`` dans le volet
construction (source par défaut « facebook »), ce qui fait apparaître
le lead dans le kanban des nouveaux prospects.

Pensé d'abord pour Facebook Lead Ads via Zapier (pas besoin de Meta
Developer App) :
- Zapier trigger  : Facebook Lead Ads → New Lead (choisis Page + Form).
- Zapier action   : Webhooks by Zapier → POST.
- URL             : ``…/api/v1/webhooks/external-lead``
- Header          : ``X-Webhook-Secret: <ton secret>``
- Body JSON       : mapper full_name, email, phone, etc. (voir
                    ``ExternalLead`` ci-dessous).

Idempotent : si l'outil source fournit ``external_id`` (ex. l'ID du
lead Facebook), une re-livraison n'est pas créée en double.

Variables d'env :
- ``EXTERNAL_LEAD_SECRET`` (requis) : chaîne aléatoire partagée avec
  l'outil source. Sans elle, le endpoint retourne 503.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DBSession
from app.models.contact_request import (
    ContactRequest,
    ContactRequestStatus,
    ProjectType,
)


log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class ExternalLead(BaseModel):
    """Payload accepté — toutes les clés sont optionnelles, mais
    au moins ``email`` ou ``phone`` doit être renseigné."""

    name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=320)
    phone: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, max_length=500)
    project_type: Optional[str] = Field(default=None, max_length=64)
    budget: Optional[str] = Field(default=None, max_length=64)
    message: Optional[str] = Field(default=None, max_length=5000)
    # Étiquette de source — sert au filtrage côté kanban. Par défaut
    # « facebook » car c'est le cas d'usage principal (Zapier ↔ FB
    # Lead Ads), mais l'outil source peut la surcharger.
    source: str = Field(default="facebook", max_length=32)
    # ID externe (ex. ID du lead Facebook) — utilisé pour dédupliquer
    # les re-livraisons. Sans, on accepte chaque appel comme nouveau.
    external_id: Optional[str] = Field(default=None, max_length=128)
    # Champs bruts supplémentaires de l'outil source, affichés dans
    # le message pour que l'opérateur voie tout dans la fiche.
    raw: Optional[dict[str, Any]] = None


_PROJECT_TYPE_MAP = {
    "cuisine": ProjectType.CUISINE.value,
    "salle_bain": ProjectType.SALLE_BAIN.value,
    "salle_de_bain": ProjectType.SALLE_BAIN.value,
    "multilogement": ProjectType.MULTILOGEMENT.value,
    "complete": ProjectType.RENOVATION_COMPLETE.value,
    "renovation_complete": ProjectType.RENOVATION_COMPLETE.value,
}


@router.post(
    "/external-lead",
    status_code=status.HTTP_200_OK,
    summary=(
        "Reçoit un lead d'un outil externe (Zapier, Make…), "
        "auth par X-Webhook-Secret"
    ),
)
async def receive_external_lead(
    payload: ExternalLead,
    db: DBSession,
    x_webhook_secret: str = Header(default="", alias="X-Webhook-Secret"),
) -> dict:
    """Crée une ContactRequest à partir d'un lead externe."""
    expected = (os.environ.get("EXTERNAL_LEAD_SECRET") or "").strip()
    if not expected:
        # On refuse explicitement plutôt que d'accepter par défaut :
        # un endpoint public sans secret = portail à spam.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="EXTERNAL_LEAD_SECRET non configuré côté serveur.",
        )
    if x_webhook_secret.strip() != expected:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Bad secret."
        )

    email = (payload.email or "").strip()
    phone = (payload.phone or "").strip()
    if not email and not phone:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Un courriel ou un téléphone est requis.",
        )

    name = (payload.name or "").strip() or "Lead externe"
    external_id = (payload.external_id or "").strip() or None

    # Idempotence : un external_id déjà vu = re-livraison, on saute.
    if external_id:
        existing = (
            await db.execute(
                select(ContactRequest)
                .where(
                    ContactRequest.source == payload.source,
                    ContactRequest.message.contains(
                        f"[external_id={external_id}]"
                    ),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {"created": False, "duplicate": True}

    # Courriel synthétique si l'outil source n'en fournit pas — la
    # colonne ``email`` de ContactRequest est NOT NULL.
    if not email or "@" not in email:
        sanitized = (
            "".join(
                c for c in (phone or external_id or "anon") if c.isalnum()
            )
            or "anon"
        )
        email = f"ext{sanitized}@external-lead.local"

    project_type_raw = (
        (payload.project_type or "").lower().replace(" ", "_")
    )
    project_type = _PROJECT_TYPE_MAP.get(
        project_type_raw, ProjectType.AUTRE.value
    )

    # Message lisible — message fourni + dump des champs bruts. On
    # ajoute aussi [external_id=…] en fin pour pouvoir détecter les
    # doublons sans changer le schéma.
    lines: list[str] = []
    if payload.message:
        lines.append(payload.message.strip())
    lines.append(f"Source : {payload.source}")
    if payload.raw:
        lines.append("")
        lines.append("Données reçues :")
        for k, v in payload.raw.items():
            if v not in (None, ""):
                lines.append(f"- {k} : {v}")
    if external_id:
        lines.append("")
        lines.append(f"[external_id={external_id}]")
    message = "\n".join(lines) or f"Lead externe reçu de {payload.source}."

    cr = ContactRequest(
        name=name[:255],
        email=email[:320],
        phone=phone[:50] if phone else None,
        address=payload.address,
        project_type=project_type,
        budget_range=payload.budget,
        message=message[:5000],
        locale="fr",
        source=payload.source[:32],
        gdpr_consent=True,
        marketing_consent=False,
        status=ContactRequestStatus.NEW.value,
    )
    db.add(cr)
    log.info(
        "Lead externe reçu (source=%s, external_id=%s)",
        payload.source,
        external_id,
    )
    return {"created": True}
