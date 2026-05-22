"""Endpoint public (no auth) — Formulaire de contact Dev Logiciel.

Permet a un prospect de soumettre une demande de devis pour un projet
de developpement logiciel via le site public. Au submit :

    POST /api/v1/public/devlog/contact

cree automatiquement un `DevlogLead` dans Kratos avec :
    - status = "new"
    - source = "web_form"
    - kanban_column = "new" (entree dans le pipeline CRM)

Anti-spam (MVP, in-memory) :
    - Honeypot field `website` (cache visuellement, les bots remplissent)
    - Rate limiting par IP : max 5 soumissions / heure / IP

Effets de bord (best-effort, n'echouent pas le endpoint) :
    - Notification interne aux managers via `notify_role`
    - Email de confirmation au prospect via Microsoft Graph

Vague 1 #7 du plan strategique Dev Logiciel.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.api.deps import DBSession
from app.models.devlog_lead import DevlogLead, LEAD_PROJECT_TYPES

log = logging.getLogger(__name__)


router = APIRouter(prefix="/public/devlog", tags=["public-devlog"])


# --------------------------- Anti-spam ---------------------------

# In-memory rate limiter — acceptable pour le MVP. A muscler avec
# Redis si volume monte (probablement jamais, c'est un form de contact).
_MAX_PER_HOUR = 5
_WINDOW_SEC = 3600
_ip_attempts: dict[str, list[float]] = {}


def _is_rate_limited(ip: Optional[str]) -> bool:
    """Retourne True si l'IP a deja envoye >= _MAX_PER_HOUR soumissions
    dans la derniere heure. Nettoie les entrees expirees au passage.
    """
    if not ip:
        return False
    now = time.time()
    cutoff = now - _WINDOW_SEC
    attempts = [t for t in _ip_attempts.get(ip, []) if t > cutoff]
    if len(attempts) >= _MAX_PER_HOUR:
        _ip_attempts[ip] = attempts
        return True
    attempts.append(now)
    _ip_attempts[ip] = attempts
    return False


def _client_ip(request: Request) -> Optional[str]:
    raw = (
        request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else None)
    )
    if raw:
        return raw.split(",")[0].strip()[:64]
    return None


# --------------------------- Schemas ---------------------------


class ContactPayload(BaseModel):
    """Payload du formulaire public Dev Logiciel.

    `website` est un honeypot : les bots remplissent les champs caches,
    les humains ne le voient pas. Si rempli, on rejette en 400 sans
    indiquer pourquoi (silent fail cote bot).
    """

    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    company: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=50)
    project_type: str = Field(default="autre", max_length=32)
    description: str = Field(..., min_length=20, max_length=5000)
    budget_range: Optional[str] = Field(default=None, max_length=64)
    locale: str = Field(default="fr", max_length=8)
    # Honeypot — doit rester vide.
    website: Optional[str] = Field(default=None, max_length=500)


class ContactAck(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    success: bool
    lead_id: Optional[int] = None
    error: Optional[str] = None


# --------------------------- Helpers ---------------------------


def _normalize_project_type(raw: str) -> str:
    """Mappe la valeur du formulaire vers un LEAD_PROJECT_TYPES valide.
    Tout ce qui ne matche pas tombe sur 'autre'.
    """
    if raw in LEAD_PROJECT_TYPES:
        return raw
    # Tolere quelques variantes communes du formulaire UX.
    aliases = {
        "site_web": "web_app",
        "website": "web_app",
        "web": "web_app",
        "mobile": "mobile_app",
        "app": "mobile_app",
        "automatisation": "automation",
        "integration": "integration",
        "conseil": "consulting",
        "audit": "consulting",
    }
    return aliases.get(raw, "autre")


async def _send_confirmation_email(
    to_email: str, name: str, project_type_label: str
) -> None:
    """Envoie l'email de confirmation au prospect via Microsoft Graph.
    N'echoue jamais le endpoint — log warning si ko.
    """
    try:
        from app.integrations.email_graph import get_mailer

        mailer = get_mailer()
        if not mailer.ready:
            log.warning(
                "Graph mailer not configured — skip confirmation email"
            )
            return

        subject = "Merci pour votre demande — Horizon Services Immobiliers"
        html_body = (
            "<div style=\"font-family: Arial, sans-serif; color: #1f2937; "
            "max-width: 560px; margin: 0 auto;\">"
            f"<p>Bonjour {name},</p>"
            "<p>Nous avons bien re&ccedil;u votre demande concernant "
            f"<strong>{project_type_label}</strong>. Notre &eacute;quipe "
            "vous recontacte sous <strong>24 heures ouvrables</strong> "
            "pour discuter de votre projet plus en d&eacute;tail.</p>"
            "<p>Si vous avez d'autres informations &agrave; nous "
            "transmettre entre-temps, vous pouvez simplement r&eacute;"
            "pondre &agrave; ce courriel.</p>"
            "<p>Cordialement,<br/>"
            "L'&eacute;quipe Horizon Services Immobiliers</p>"
            "<hr style=\"border:none;border-top:1px solid #e5e7eb;"
            "margin:24px 0;\"/>"
            "<p style=\"font-size:12px;color:#6b7280;\">"
            "Horizon Services Immobiliers &mdash; "
            "<a href=\"https://immohorizon.com\">immohorizon.com</a>"
            "</p>"
            "</div>"
        )
        await mailer.send(to=[to_email], subject=subject, html_body=html_body)
    except Exception as exc:  # pragma: no cover
        log.warning("Confirmation email failed for %s : %s", to_email, exc)


# Label francais pour l'email — different des codes techniques internes.
_PROJECT_TYPE_LABELS_FR = {
    "web_app": "une application/site web",
    "mobile_app": "une application mobile",
    "automation": "une automatisation",
    "integration": "une integration",
    "consulting": "un mandat de conseil",
    "autre": "votre projet",
}


# --------------------------- Routes ---------------------------


@router.post(
    "/contact",
    response_model=ContactAck,
    status_code=status.HTTP_201_CREATED,
    summary="(Public) Soumet une demande de devis Dev Logiciel",
)
async def submit_contact(
    payload: ContactPayload,
    request: Request,
    db: DBSession,
) -> ContactAck:
    # 1. Honeypot — bot detecte. On renvoie un 400 generique.
    if payload.website and payload.website.strip():
        log.info("Honeypot triggered for devlog/contact (likely bot)")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid submission.",
        )

    # 2. Rate limit IP.
    ip = _client_ip(request)
    if _is_rate_limited(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de soumissions. Reessayez dans une heure.",
        )

    # 3. Normalisation du payload.
    name = payload.name.strip()[:255]
    email = str(payload.email).strip()[:320]
    company = (payload.company or "").strip()[:255] or None
    phone = (payload.phone or "").strip()[:50] or None
    description = payload.description.strip()[:5000]
    budget_range = (payload.budget_range or "").strip()[:64] or None
    project_type = _normalize_project_type(payload.project_type)
    locale = payload.locale if payload.locale in ("fr", "en") else "fr"

    # 4. Creation du lead.
    lead = DevlogLead(
        name=name,
        company=company,
        email=email,
        phone=phone,
        project_type=project_type,
        source="web_form",
        status="new",
        kanban_column="new",
        position=0,
        locale=locale,
        project_summary=description,
        budget_range=budget_range,
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)

    # 5. Notification interne (best-effort).
    try:
        from app.services.notifications import notify_role

        await notify_role(
            db,
            min_role="manager",
            kind="devlog.lead.created",
            title=f"Nouveau lead web : {name}",
            body=(
                f"{email} | {project_type} | "
                f"{description[:160]}"
            ),
            href=f"/dev-logiciel/leads/{lead.id}",
        )
    except Exception as exc:  # pragma: no cover
        log.warning("notify_role failed for devlog lead %s : %s", lead.id, exc)

    # 6. Email de confirmation au prospect (best-effort).
    try:
        label = _PROJECT_TYPE_LABELS_FR.get(project_type, "votre projet")
        await _send_confirmation_email(email, name, label)
    except Exception as exc:  # pragma: no cover
        log.warning("Confirmation email failed for lead %s : %s", lead.id, exc)

    return ContactAck(success=True, lead_id=lead.id)
