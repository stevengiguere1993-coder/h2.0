"""Téléphonie — endpoints webhook Twilio + admin minimal.

Phase 1 (transfert direct) + Phase 2 (secrétaire IA Polly Neural) :

    POST /api/v1/voice/twilio/voice       — décrocher un appel entrant
    POST /api/v1/voice/twilio/secretary   — tour de conversation IA
    POST /api/v1/voice/twilio/status      — callback de fin d'appel
    GET  /api/v1/voice/phone-numbers      — liste (admin)
    GET  /api/v1/voice/calls              — journal récent (admin)
    GET  /api/v1/voice/calls/{id}/turns   — transcription d'un appel
    PATCH /api/v1/voice/phone-numbers/{id} — toggle secretary_mode (admin)

Les webhooks `twilio/*` sont publics mais vérifient la signature
HMAC X-Twilio-Signature. Les endpoints admin requièrent `CurrentAdmin`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentAdmin, CurrentUser, DBSession
from app.integrations.voice import get_voice_provider
from app.integrations.voice.routing import RoutingAction, decide_routing
from app.integrations.voice.caller_identity import (
    CallerKind,
    build_identity_context_block,
    build_personalized_greeting,
    identify_caller,
)
from app.integrations.voice.lead_outbound import (
    build_outbound_system_prompt,
    decide_lead_outbound_turn,
)
from app.integrations.voice.secretary import (
    decide_initial_greeting,
    decide_next_turn,
)
from app.integrations.voice.spam_filter import (
    SpamCheckResult,
    check_incoming,
    maybe_mark_honeypot,
    record_call_cost,
    record_spam_block,
)
from app.integrations.voice.voice_sdk import (
    build_dial_clients_xml,
    generate_access_token,
    list_online_user_ids,
    update_presence,
    voice_sdk_configured,
)
from app.integrations.voice.twilio_provider import TwilioVoiceProvider
from app.models.contact_request import ContactRequest, ContactRequestStatus
from app.models.voice import (
    Call,
    CallDirection,
    CallStatus,
    CallTurn,
    PhoneNumber,
    VoiceBusinessHours,
    VoiceFilter,
    VoiceSms,
    VoiceUsageDaily,
)
from app.models.email_log import EmailLog

log = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])


@router.get("/calls/{call_id}/recording")
async def stream_call_recording(
    call_id: int, db: DBSession, user: CurrentUser
) -> Response:
    """Streame l'enregistrement (voicemail / appel) à travers Kratos pour
    qu'il s'écoute DANS le portail, sans renvoyer l'utilisateur vers
    Twilio. On proxy le média Twilio avec l'auth Basic du compte (les URLs
    Twilio ne sont pas publiques) et on renvoie un audio/mpeg.
    """
    import base64

    import httpx

    call = await db.get(Call, call_id)
    if call is None or not call.recording_url:
        raise HTTPException(status_code=404, detail="Enregistrement introuvable.")

    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if not sid or not token:
        raise HTTPException(
            status_code=503, detail="Twilio non configuré (creds manquantes)."
        )

    # L'URL Twilio peut être l'API recording sans extension : on force .mp3
    # pour récupérer le média audio plutôt que le JSON de métadonnées.
    url = call.recording_url
    if not url.lower().endswith((".mp3", ".wav")):
        url = f"{url}.mp3"

    basic = base64.b64encode(f"{sid}:{token}".encode()).decode("ascii")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
            r = await http.get(url, headers={"Authorization": f"Basic {basic}"})
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Échec de récupération Twilio.")
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Twilio a répondu {r.status_code} pour l'enregistrement.",
        )

    media_type = r.headers.get("content-type", "audio/mpeg")
    return Response(
        content=r.content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _full_request_url(request: Request) -> str:
    """URL absolue telle que Twilio l'a calculée pour signer.

    Render termine TLS devant l'app, donc `request.url` est en `http://`
    interne. On reconstruit en `https://` via le header `X-Forwarded-Proto`
    quand il est présent, et `X-Forwarded-Host` pour le domaine public.
    """
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not host:
        return str(request.url)
    path = request.url.path
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{proto}://{host}{path}{query}"


def _secretary_base_url() -> str:
    return (
        os.getenv("VOICE_WEBHOOK_BASE_URL") or "https://h2-0.onrender.com"
    ).rstrip("/")


def _secretary_action_url() -> str:
    return f"{_secretary_base_url()}/api/v1/voice/twilio/secretary"


def _voicemail_action_url() -> str:
    return f"{_secretary_base_url()}/api/v1/voice/twilio/voicemail"


def _voicemail_transcribe_url() -> str:
    return f"{_secretary_base_url()}/api/v1/voice/twilio/voicemail-transcript"


def _voice_sdk_callback_url() -> str:
    return f"{_secretary_base_url()}/api/v1/voice/twilio/sdk-outbound"


def _outbound_bridge_url(call_id: int) -> str:
    return (
        f"{_secretary_base_url()}"
        f"/api/v1/voice/twilio/outbound-bridge?call_id={int(call_id)}"
    )


SUPPORTED_ENTITY_TYPES = {
    "prospection_lead",
    "contact_request",
    "client",
    "contact",
}


def _normalize_e164(raw: str) -> str:
    """Normalise un numéro en format E.164 NANP (+1XXXXXXXXXX).

    Tolérant aux env vars mal saisies (sans `+`, avec espaces ou
    parenthèses) : `14388002979` → `+14388002979`, `(438) 800-2979` →
    `+14388002979`, `+14388002979` → `+14388002979`.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith("+"):
        # Garde le + initial, ne garde que les chiffres après.
        digits = "".join(c for c in s[1:] if c.isdigit())
        return f"+{digits}" if digits else ""
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) >= 8:
        return f"+{digits}"
    return ""


def _parse_e164_list(raw: str) -> list[str]:
    """Parse une chaîne potentiellement multi-numéros séparés par
    virgule / point-virgule / espace en liste de numéros E.164
    normalisés. Permet à un user de mettre plusieurs cibles dans un
    champ « cible de transfert » et qu'on ring tout le monde en
    parallèle (premier qui décroche gagne).
    """
    if not raw:
        return []
    out: list[str] = []
    for chunk in raw.replace(";", ",").replace(" ", ",").split(","):
        n = _normalize_e164(chunk.strip())
        if n and n not in out:
            out.append(n)
    return out


async def _validate_twilio_signature(request: Request) -> dict[str, str]:
    """Lit le body form-encoded, vérifie la signature, retourne les params."""
    try:
        provider = get_voice_provider()
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice provider not configured",
        )

    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    sig = request.headers.get("x-twilio-signature", "")
    url = _full_request_url(request)
    if not provider.validate_webhook_signature(url, params, sig):
        log.warning("Twilio signature mismatch on url=%s", url)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Twilio signature",
        )
    return params


def _twilio_provider() -> TwilioVoiceProvider:
    """Cast vers le provider concret (méthodes TwiML spécifiques)."""
    p = get_voice_provider()
    if not isinstance(p, TwilioVoiceProvider):  # pragma: no cover
        raise HTTPException(
            status_code=500, detail="Expected Twilio provider for TwiML"
        )
    return p


async def _record_turn(
    db,
    *,
    call_id: int,
    role: str,
    text: str,
    confidence: Optional[float] = None,
) -> None:
    """Insère un CallTurn (role ∈ {user, assistant}) à la suite du dernier."""
    count = (
        await db.execute(
            select(CallTurn).where(CallTurn.call_id == call_id)
        )
    ).scalars().all()
    next_idx = len(count)
    db.add(
        CallTurn(
            call_id=call_id,
            turn_index=next_idx,
            role=role,
            text=text,
            confidence=int(confidence * 100) if confidence is not None else None,
        )
    )
    await db.flush()


async def _create_lead_from_callback(db, *, call: Call) -> Optional[int]:
    """Crée un ContactRequest depuis les infos capturées par la secrétaire.

    Email synthétisé depuis le numéro car notre table impose un email
    non-NULL ; le staff CRM identifie facilement les leads téléphoniques
    par `source='telephonie'` (filtre de la kanban).
    """
    if call.contact_request_id is not None:
        return call.contact_request_id

    callback_phone = (
        (call.lead_callback_phone or "").strip()
        or call.from_e164
    )
    name = (call.lead_name or "").strip() or f"Appelant {call.from_e164}"
    # Construit un message lisible depuis ce qu'on a.
    bits: list[str] = []
    if call.lead_reason:
        bits.append(call.lead_reason)
    if call.intent and call.intent not in ("unclear", "callback"):
        bits.append(f"Intent détecté : {call.intent}")
    bits.append(f"Numéro entrant : {call.from_e164}")
    message = " — ".join(bits) or "Appel reçu via la secrétaire IA."

    # Email synthétique stable par numéro (réutilisable pour matcher
    # les rappels successifs au même prospect au lieu d'en créer plein).
    sanitized = "".join(c for c in callback_phone if c.isalnum()) or "anon"
    synth_email = f"tel{sanitized}@telephonie.local"

    cr = ContactRequest(
        name=name[:255],
        email=synth_email,
        phone=callback_phone[:50],
        project_type="autre",
        message=message[:5000],
        locale="fr" if call.lang.startswith("fr") else "en",
        source="telephonie",
        gdpr_consent=True,
        marketing_consent=False,
        status=ContactRequestStatus.NEW.value,
    )
    db.add(cr)
    await db.flush()
    call.contact_request_id = cr.id
    await db.flush()
    return cr.id


# ---------------------------------------------------------------------
# Helpers : intake construction + routage suivi projet (Phase 8)
# ---------------------------------------------------------------------


async def _create_intake_contact_request(
    db, *, call: "Call", intake_data: dict
) -> Optional[int]:
    """Crée un ContactRequest depuis l'intake construction collecté
    par Léa au téléphone. Génère un `validation_token` unique,
    déclenche l'envoi du courriel récapitulatif au client (en
    BackgroundTask via httpx pour ne pas bloquer la réponse TwiML).
    """
    import secrets

    from app.models.contact_request import (
        ContactRequest,
        ContactRequestStatus,
        ProjectType,
    )

    if call.contact_request_id is not None:
        return call.contact_request_id

    name = (
        (call.lead_name or "").strip()
        or f"Appelant {call.from_e164}"
    )[:255]

    intake_email = (intake_data or {}).get("email", "").strip()
    callback_phone = (
        (call.lead_callback_phone or "").strip()
        or call.from_e164
    )

    if intake_email and "@" in intake_email:
        email = intake_email[:320]
    else:
        # Email synthétique stable par numéro — l'équipe pourra
        # mettre à jour quand le client validera.
        sanitized = "".join(
            c for c in callback_phone if c.isalnum()
        ) or "anon"
        email = f"tel{sanitized}@telephonie.local"

    project_type_raw = (intake_data or {}).get("type_travaux", "").lower()
    project_type_map = {
        "cuisine": ProjectType.CUISINE.value,
        "salle_bain": ProjectType.SALLE_BAIN.value,
        "salle de bain": ProjectType.SALLE_BAIN.value,
        "multilogement": ProjectType.MULTILOGEMENT.value,
        "complete": ProjectType.RENOVATION_COMPLETE.value,
    }
    project_type = project_type_map.get(
        project_type_raw, ProjectType.AUTRE.value
    )

    # Message lisible pour la fiche CRM — résumé visuel des champs
    # collectés (utilisé aussi dans le courriel HTML).
    bits: list[str] = ["Demande captée par Léa (secrétaire IA) au téléphone.", ""]
    labels = {
        "type_travaux": "Type de travaux",
        "adresse": "Adresse du projet",
        "echeancier": "Échéancier souhaité",
        "budget": "Budget envisagé",
        "best_callback_time": "Meilleur moment pour rappeler",
    }
    for key, label in labels.items():
        v = (intake_data or {}).get(key)
        if v:
            bits.append(f"- {label} : {v}")
    if call.lead_reason:
        bits.append("")
        bits.append(f"Note : {call.lead_reason}")
    message = "\n".join(bits) or "Intake téléphonique."

    token = secrets.token_urlsafe(32)

    cr = ContactRequest(
        name=name,
        email=email,
        phone=callback_phone[:50],
        address=(intake_data or {}).get("adresse"),
        project_type=project_type,
        budget_range=(intake_data or {}).get("budget"),
        message=message[:5000],
        locale="fr" if call.lang.startswith("fr") else "en",
        source="telephonie_intake_ia",
        gdpr_consent=True,
        marketing_consent=False,
        status=ContactRequestStatus.NEW.value,
        intake_data=json.dumps(intake_data or {}, ensure_ascii=False),
        validation_token=token,
    )
    db.add(cr)
    await db.flush()
    call.contact_request_id = cr.id
    await db.flush()

    # Envoi du courriel récapitulatif au client (best-effort — si
    # Microsoft Graph est down, on log et on continue, le staff
    # rappellera de toute façon).
    if intake_email and "@" in intake_email:
        try:
            await _send_intake_validation_email(
                to_email=intake_email,
                name=name,
                token=token,
                intake_data=intake_data or {},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Intake validation email failed (cr=%s): %s", cr.id, exc
            )

    return cr.id


async def _send_intake_validation_email(
    *, to_email: str, name: str, token: str, intake_data: dict
) -> None:
    """Envoie au prospect le courriel récapitulatif de l'intake
    téléphonique avec lien vers la page de validation publique."""
    from app.integrations.email_graph import get_mailer
    from app.core.config import settings

    base_url = (
        getattr(settings, "frontend_base_url", None)
        or os.getenv("FRONTEND_BASE_URL")
        or os.getenv("PUBLIC_BASE_URL")
        or "https://horizonservicesimmobiliers.com"
    ).rstrip("/")
    validation_url = f"{base_url}/fr/valider-demande/{token}"

    labels = {
        "type_travaux": "Type de travaux",
        "adresse": "Adresse du projet",
        "echeancier": "Échéancier souhaité",
        "budget": "Budget envisagé",
        "best_callback_time": "Meilleur moment pour vous rappeler",
    }
    rows = []
    for key, label in labels.items():
        v = (intake_data or {}).get(key)
        if v:
            rows.append(
                f'<tr><td style="padding:6px 12px;color:#666;">{label}</td>'
                f'<td style="padding:6px 12px;color:#111;"><strong>{v}</strong></td></tr>'
            )
    rows_html = "\n".join(rows) or '<tr><td colspan="2" style="padding:12px;color:#666;">Aucun détail capté.</td></tr>'

    html_body = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;margin:auto;padding:24px;">
  <h2 style="color:#0b3d2e;margin:0 0 12px;">Bonjour {name},</h2>
  <p style="color:#333;line-height:1.5;">
    Merci pour votre appel à Horizon Services Immobiliers. Voici le
    résumé de votre demande tel que captée par notre secrétaire IA.
    Pouvez-vous vérifier que tout est correct&nbsp;? Vous pouvez aussi
    <strong>ajouter des photos</strong> de l'espace concerné — ça
    nous aide énormément à préparer un devis précis.
  </p>
  <table cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;background:#f6f7f9;border-radius:8px;margin:18px 0;">
    {rows_html}
  </table>
  <p style="text-align:center;margin:28px 0;">
    <a href="{validation_url}"
       style="display:inline-block;background:#d4af37;color:#0b1f1a;text-decoration:none;
              padding:14px 28px;border-radius:8px;font-weight:700;font-size:15px;">
      Valider ma demande &amp; ajouter des photos →
    </a>
  </p>
  <p style="color:#555;line-height:1.5;font-size:14px;">
    Nous vous rappellerons sous peu pour fixer un rendez-vous sur place.<br>
    Si une information n'est pas correcte, modifiez-la directement
    depuis le lien ci-dessus.
  </p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
  <p style="color:#999;font-size:12px;text-align:center;">
    Horizon Services Immobiliers — Montréal, Québec<br>
    Cet email vous a été envoyé suite à votre appel téléphonique.
  </p>
</div>
"""
    subject = f"Votre demande à Horizon — résumé à valider ({name})"
    mailer = get_mailer()
    await mailer.send(to=[to_email], subject=subject, html_body=html_body)


async def _find_project_lead_phone(
    db, *, call: "Call"
) -> Optional[str]:
    """Renvoie le téléphone du premier ProjectMember actif du projet
    lié à l'appelant. Si aucun ProjectMember n'a de phone, fallback
    sur le `followup_forward_e164` configuré sur le PhoneNumber appelé
    (back-office / réception). Utilisé pour transfer_project_lead."""
    project = await _find_project_for_call(db, call)
    if project:
        from app.models.employe import Employe
        from app.models.project_member import ProjectMember
        from app.models.user import User

        rows = (
            await db.execute(
                select(User.email)
                .join(ProjectMember, ProjectMember.user_id == User.id)
                .where(
                    ProjectMember.project_id == project.id,
                    User.is_active.is_(True),
                )
            )
        ).all()
        emails = [r[0] for r in rows if r[0]]
        if emails:
            emp = (
                await db.execute(
                    select(Employe.phone)
                    .where(
                        Employe.email.in_(emails),
                        Employe.phone.is_not(None),
                    )
                    .limit(1)
                )
            ).first()
            if emp and emp[0]:
                return emp[0]

    # Fallback : numéro back-office configuré sur le PhoneNumber appelé.
    pn = (
        await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.id == call.phone_number_id
            )
        )
    ).scalar_one_or_none()
    if pn and pn.followup_forward_e164:
        return pn.followup_forward_e164
    return None


async def _find_project_lead_online_user_ids(
    db, *, call: "Call"
) -> List[int]:
    """Renvoie les `user_id` des membres du projet ACTUELLEMENT
    « online » dans le portail (Voice SDK heartbeat). On ring d'abord
    ceux-là via WebRTC (gratuit + reach instantané)."""
    project = await _find_project_for_call(db, call)
    if not project:
        return []
    from app.models.project_member import ProjectMember

    member_ids = (
        await db.execute(
            select(ProjectMember.user_id).where(
                ProjectMember.project_id == project.id
            )
        )
    ).scalars().all()
    if not member_ids:
        return []
    online = await list_online_user_ids(db)
    return [uid for uid in online if uid in set(member_ids)]


async def _immeuble_urgence_phone_for_call(db, call: "Call") -> Optional[str]:
    """Numéro d'urgence de l'immeuble du locataire appelant.

    Résout : Call.entity_id (locataire) → bail actif → logement →
    immeuble.urgence_phone. Retourne None si l'appelant n'est pas un
    locataire identifié, ou si son immeuble n'a pas de contact d'urgence
    (on basculera alors sur le numéro de garde global).
    """
    if call.entity_type != "locataire" or not call.entity_id:
        return None
    try:
        from app.models.immobilier import (
            Bail,
            BailStatus,
            Immeuble,
            Logement,
        )

        row = (
            await db.execute(
                select(Immeuble.urgence_phone)
                .join(Logement, Logement.immeuble_id == Immeuble.id)
                .join(Bail, Bail.logement_id == Logement.id)
                .where(
                    Bail.locataire_id == call.entity_id,
                    Bail.status == BailStatus.ACTIF.value,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return (row or "").strip() or None
    except Exception:  # noqa: BLE001
        return None


async def _notify_owners_urgence(db, *, call: "Call", reason: str) -> None:
    """Notif cloche urgente envoyée à TOUS les owners — un appel
    URGENCE LOCATAIRE doit toujours déclencher une alerte visible
    dans le portail, peu importe qui répond au transfert. Push aussi
    si VAPID configuré (réveille le téléphone même si app fermée)."""
    try:
        from app.integrations.webpush import push_to_users
        from app.models.notification import Notification
        from app.models.user import User

        owners = (
            await db.execute(
                select(User.id).where(User.role.in_(("owner", "admin")))
            )
        ).scalars().all()
        title = f"🚨 URGENCE — {call.from_e164}"
        body = (reason or "Urgence détectée par Léa")[:500]
        href = f"/telephonie?call={call.id}"
        for uid in owners:
            db.add(
                Notification(
                    user_id=uid,
                    kind="urgence_locataire",
                    title=title,
                    body=body,
                    href=href,
                )
            )
        await db.flush()
        # Push best-effort en parallèle (no-op si VAPID pas configuré).
        try:
            await push_to_users(
                db,
                user_ids=list(owners),
                title=title,
                body=body,
                href=href,
                tag=f"urgence-{call.id}",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Urgence push failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("Urgence notification failed: %s", exc)


async def _propose_appointment_slots(
    db, *, call: "Call", intake_data: dict
) -> list[dict]:
    """Cherche les 3 meilleurs créneaux libres pour un closer et les
    mémorise dans intake_data['proposed_slots']. Retourne la liste
    serialisée (str-friendly pour Polly) à annoncer à l'appelant."""
    from app.models.appointment_type import AppointmentType
    from app.services.agenda_slot_finder import find_available_slots

    # Type « évaluation soumission » par défaut (seedé au boot).
    apt_type = (
        await db.execute(
            select(AppointmentType).where(
                AppointmentType.slug == "evaluation_soumission",
                AppointmentType.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if apt_type is None:
        return []
    location = (intake_data or {}).get("adresse") or ""
    slots = await find_available_slots(
        db,
        appointment_type_id=apt_type.id,
        location=location or None,
        role_kind="closer",
        days_ahead=7,
        max_results=3,
    )
    if not slots:
        return []
    out = []
    for s in slots:
        out.append(
            {
                "user_id": s.user_id,
                "user_display": s.user_display,
                "start_at": s.start_at.isoformat(),
                "end_at": s.end_at.isoformat(),
                "appointment_type_id": s.appointment_type_id,
            }
        )
    # Persiste les slots sur le Call.session_state pour les retrouver
    # quand Léa retournera next_action=book_slot au tour suivant.
    state = {}
    if call.session_state:
        try:
            state = json.loads(call.session_state) or {}
        except Exception:
            state = {}
    state["proposed_slots"] = out
    # On garde aussi un snapshot de l'intake en cours pour pouvoir
    # créer le ContactRequest au moment du book_slot.
    state["intake_data"] = intake_data
    call.session_state = json.dumps(state, ensure_ascii=False)
    await db.flush()
    return out


_FR_WEEKDAYS = [
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"
]
_FR_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
_EN_WEEKDAYS = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]


def _format_slots_announcement(slots: list[dict], *, lang: str) -> str:
    """Convertit la liste de créneaux en phrase lisible par Polly."""
    if not slots:
        return (
            "Aucune disponibilité, désolée."
            if lang.startswith("fr")
            else "No availability, sorry."
        )
    parts = []
    for i, s in enumerate(slots, 1):
        dt = datetime.fromisoformat(s["start_at"])
        if lang.startswith("fr"):
            day = _FR_WEEKDAYS[dt.weekday()]
            hour = dt.strftime("%-Hh%M" if dt.minute else "%-Hh")
            parts.append(f"{i}) {day} à {hour}")
        else:
            day = _EN_WEEKDAYS[dt.weekday()]
            hour = dt.strftime("%-I:%M %p" if dt.minute else "%-I %p")
            parts.append(f"{i}) {day} at {hour}")
    listing = ", ".join(parts)
    if lang.startswith("fr"):
        return (
            f"Voici les disponibilités pour une visite d'évaluation : "
            f"{listing}. Lequel vous convient ?"
        )
    return (
        f"Here are the available slots for an evaluation visit: "
        f"{listing}. Which one works for you?"
    )


async def _book_chosen_slot(
    db,
    *,
    call: "Call",
    intake_data: dict,
    chosen_index: int,
) -> bool:
    """Crée l'AgendaEvent à partir du slot choisi par l'appelant.
    Crée aussi le ContactRequest si pas déjà fait. Envoie SMS de
    confirmation + push au closer. Renvoie True si OK, False sinon."""
    proposed = intake_data.get("proposed_slots") or []
    if not (0 <= chosen_index < len(proposed)):
        return False
    chosen = proposed[chosen_index]

    # Crée le ContactRequest (si pas déjà fait) avec les infos d'intake.
    if call.contact_request_id is None:
        cr_id = await _create_intake_contact_request(
            db, call=call, intake_data=intake_data
        )
    else:
        cr_id = call.contact_request_id

    from app.models.agenda_event import AgendaEvent
    from app.models.appointment_type import AppointmentType

    # Re-vérifie la dispo (anti-race condition : un autre RV a pu
    # être créé entre la proposition et le choix).
    from app.services.agenda_availability import check_slot_availability

    start_at = datetime.fromisoformat(chosen["start_at"])
    end_at = datetime.fromisoformat(chosen["end_at"])
    apt_type = (
        await db.execute(
            select(AppointmentType).where(
                AppointmentType.id == chosen["appointment_type_id"]
            )
        )
    ).scalar_one_or_none()
    prep = (apt_type.prep_buffer_min if apt_type else 0) or 0
    recheck = await check_slot_availability(
        db,
        user_id=chosen["user_id"],
        start_at=start_at,
        end_at=end_at,
        location=intake_data.get("adresse") or None,
        prep_buffer_min=prep,
    )
    if not recheck.is_available:
        log.info(
            "Slot no longer available for call %s (conflicts: %s)",
            call.id, recheck.conflicts,
        )
        return False

    title = (
        f"Évaluation soumission — "
        f"{(call.lead_name or 'Prospect').strip()}"
    )[:255]
    event = AgendaEvent(
        title=title,
        description=(
            f"RV pris au téléphone par Léa.\n"
            f"Téléphone : {call.from_e164}\n"
            f"Type travaux : {(intake_data.get('type_travaux') or '—')}\n"
            f"Budget : {(intake_data.get('budget') or '—')}\n"
            f"Échéancier : {(intake_data.get('echeancier') or '—')}"
        ),
        location=(intake_data.get("adresse") or None),
        start_at=start_at,
        end_at=end_at,
        all_day=False,
        scope="construction",
        assignee_user_id=chosen["user_id"],
        contact_request_id=cr_id,
        event_type="rdv",
        appointment_type_id=chosen["appointment_type_id"],
    )
    db.add(event)
    await db.flush()
    call.contact_request_id = cr_id
    call.intent = "intake_construction"
    call.lead_reason = (
        (call.lead_reason or "") + f" [BOOKED {start_at.isoformat()}]"
    ).strip()

    # SMS de confirmation au prospect
    try:
        await _send_booking_confirmation_sms(
            call=call,
            user_display=chosen["user_display"],
            start_at=start_at,
            location=intake_data.get("adresse") or "",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Booking SMS failed: %s", exc)

    # Push notification au closer + cloche
    try:
        await _notify_closer_new_booking(
            db,
            closer_user_id=chosen["user_id"],
            event_id=event.id,
            prospect_name=(call.lead_name or call.from_e164),
            start_at=start_at,
            location=intake_data.get("adresse") or "",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Booking notif failed: %s", exc)

    return True


async def _send_booking_confirmation_sms(
    *,
    call: "Call",
    user_display: str,
    start_at: datetime,
    location: str,
) -> None:
    """Envoie un SMS de confirmation au numéro appelant après booking.
    Utilise l'API REST Twilio directement via httpx (cohérent avec le
    reste du codebase qui n'utilise pas le SDK officiel)."""
    import base64

    import httpx

    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_num = _normalize_e164(os.getenv("TWILIO_PHONE_NUMBER", ""))
    if not sid or not token or not from_num:
        log.info("Booking SMS skipped — Twilio creds missing")
        return
    body_fr = (
        f"Horizon Services Immobiliers : votre RV avec {user_display} "
        f"est confirmé pour {_human_datetime_fr(start_at)}"
        f"{(' au ' + location) if location else ''}. "
        f"À bientôt !"
    )
    basic = base64.b64encode(f"{sid}:{token}".encode()).decode("ascii")
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            r = await http.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "To": call.from_e164,
                    "From": from_num,
                    "Body": body_fr[:1500],
                },
            )
            if r.status_code >= 400:
                log.warning(
                    "Booking SMS failed: %s %s", r.status_code, r.text[:200]
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("Booking SMS exception: %s", exc)


def _human_datetime_fr(dt: datetime) -> str:
    day = _FR_WEEKDAYS[dt.weekday()]
    month = _FR_MONTHS[dt.month - 1]
    hour = dt.strftime("%-Hh%M" if dt.minute else "%-Hh")
    return f"{day} {dt.day} {month} à {hour}"


async def _notify_closer_new_booking(
    db,
    *,
    closer_user_id: int,
    event_id: int,
    prospect_name: str,
    start_at: datetime,
    location: str,
) -> None:
    """Notif cloche + push au closer pour son nouveau RV booké par Léa."""
    from app.integrations.webpush import push_to_user
    from app.models.notification import Notification

    title = f"📅 Nouveau RV — {prospect_name}"
    body = (
        f"Léa a booké un RV pour vous le {_human_datetime_fr(start_at)}"
        f"{(' au ' + location) if location else ''}."
    )
    href = f"/app/agenda?event={event_id}"
    db.add(
        Notification(
            user_id=closer_user_id,
            kind="agenda_booked_by_ai",
            title=title,
            body=body,
            href=href,
        )
    )
    await db.flush()
    try:
        await push_to_user(
            db,
            user_id=closer_user_id,
            title=title,
            body=body,
            href=href,
            tag=f"booking-{event_id}",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Closer push failed: %s", exc)


async def _find_project_for_call(db, call: "Call"):
    """Trouve un projet ACTIF pour l'appelant identifié (CLIENT ou
    LOCATAIRE avec projet en cours). Renvoie None sinon."""
    if not call.entity_type or not call.entity_id:
        return None
    from app.models.project import Project

    if call.entity_type == "client":
        proj = (
            await db.execute(
                select(Project)
                .where(Project.client_id == call.entity_id)
                .order_by(Project.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return proj
    if call.entity_type == "contact_request":
        proj = (
            await db.execute(
                select(Project)
                .where(Project.contact_request_id == call.entity_id)
                .order_by(Project.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return proj
    return None


# ---------------------------------------------------------------------
# Helper : fallback TwiML en cas d'erreur inattendue
# ---------------------------------------------------------------------


def _safe_error_twiml(lang: str = "fr-CA") -> Response:
    """TwiML servi quand un handler webhook lève une exception. Évite
    le « We are sorry, an application error has occurred » par défaut
    de Twilio qui sonne très moche pour l'appelant."""
    if lang.startswith("en"):
        say = (
            "Sorry, we are experiencing a technical issue. "
            "Please try again in a few minutes. Goodbye."
        )
        voice = "Polly.Joanna-Neural"
    else:
        say = (
            "Désolée, nous rencontrons un souci technique. "
            "Réessayez dans quelques minutes ou laissez-nous un message "
            "par texto. Au revoir."
        )
        # Voix française québécoise (fr-CA) — la voix Léa est fr-FR
        # et provoque « application error » côté Twilio si mismatch.
        voice = "Polly.Gabrielle-Neural"
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say voice="{voice}" language="{lang}">{say}</Say>'
        "<Hangup/>"
        "</Response>"
    )
    return Response(content=twiml, media_type="application/xml")


# ---------------------------------------------------------------------
# Webhook : appel entrant
# ---------------------------------------------------------------------


@router.post(
    "/twilio/voice",
    summary="Webhook Twilio : appel entrant — répond en TwiML",
    response_class=Response,
)
async def twilio_incoming_call(request: Request, db: DBSession) -> Response:
    """Wrapper défensif : toute exception non-HTTPException renvoie un
    TwiML poli en français au lieu du message d'erreur Twilio."""
    try:
        return await _twilio_incoming_call_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_incoming_call failed")
        return _safe_error_twiml()


async def _twilio_incoming_call_impl(request: Request, db: DBSession) -> Response:
    """Décroche un appel entrant.

    Selon `PhoneNumber.secretary_mode_active` :
    - True  → renvoie la phrase d'accueil + un <Gather> qui rebondit
              sur `/twilio/secretary` à chaque tour.
    - False → comportement Phase 1 : <Dial> direct vers forward_to.
    """
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()

    call_sid = params.get("CallSid", "")
    from_e164 = params.get("From", "")
    to_e164 = params.get("To", "")

    if not (call_sid and from_e164 and to_e164):
        raise HTTPException(status_code=400, detail="Missing CallSid / From / To")

    pn = (
        await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.e164 == to_e164, PhoneNumber.active.is_(True)
            )
        )
    ).scalar_one_or_none()

    if pn is None:
        # Self-healing : si le numéro qu'on reçoit correspond à
        # TWILIO_PHONE_NUMBER de l'env, le bootstrap a soit échoué soit
        # n'a pas encore tourné. On crée la ligne à la volée pour que
        # l'appel ne soit pas perdu — ça évite de devoir relancer un
        # bootstrap manuel quand quelque chose foire au démarrage.
        # Normalisation E.164 tolérante pour rattraper les env vars
        # mal saisies (sans `+`, avec espaces, etc.).
        env_number = _normalize_e164(os.getenv("TWILIO_PHONE_NUMBER") or "")
        if to_e164 == env_number and env_number:
            log.warning(
                "Self-heal : aucune ligne PhoneNumber pour %s, création à la volée",
                to_e164,
            )
            pn = PhoneNumber(
                e164=to_e164,
                provider="twilio",
                label="Ligne principale (auto-créée)",
                forward_to_e164=(os.getenv("TWILIO_FORWARD_TO") or None),
                active=True,
            )
            db.add(pn)
            await db.flush()
        else:
            log.warning(
                "Incoming call to unknown number %s (CallSid=%s, env=%s)",
                to_e164, call_sid, env_number or "(non set)",
            )
            twiml = provider.build_say_and_hangup(
                say=(
                    "Ce numéro n'est pas configuré dans notre système. "
                    "Au revoir."
                ),
                lang="fr-CA",
            )
            return Response(content=twiml, media_type="application/xml")

    forward_to = (
        (pn.forward_to_e164 or os.getenv("TWILIO_FORWARD_TO") or "").strip()
    )

    # Idempotent : Twilio rejoue parfois le webhook initial.
    existing = (
        await db.execute(select(Call).where(Call.provider_sid == call_sid))
    ).scalar_one_or_none()
    if existing is None:
        existing = Call(
            phone_number_id=pn.id,
            provider_sid=call_sid,
            direction=CallDirection.INBOUND.value,
            status=CallStatus.RINGING.value,
            from_e164=from_e164,
            to_e164=to_e164,
            forwarded_to_e164=forward_to or None,
            lang="fr-CA",
        )
        db.add(existing)
        await db.flush()

    # ----- Identification CRM de l'appelant -----
    # Lookup phone dans client / locataire / lead_prospection / lead_web.
    # On stocke caller_kind + entity_type+entity_id pour la fiche, et
    # on garde l'objet `identified` pour personnaliser le greeting + le
    # system prompt secrétaire ci-dessous.
    identified = await identify_caller(db, from_e164)
    existing.caller_kind = identified.kind.value
    if identified.kind != CallerKind.UNKNOWN and identified.entity_id:
        # Le mapping kind → entity_type table name :
        kind_to_entity = {
            CallerKind.CLIENT: "client",
            CallerKind.LOCATAIRE: "locataire",
            CallerKind.LEAD_PROSPECTION: "prospection_lead",
            CallerKind.LEAD_WEB: "contact_request",
        }
        existing.entity_type = kind_to_entity.get(identified.kind)
        existing.entity_id = identified.entity_id

    # ----- Anti-spam (6 couches) -----
    # Évalué AVANT toute action coûteuse. Si bloqué, on Reject ou on
    # bascule en voicemail-only sans facturer Polly + Claude.
    # Exception : si l'appelant est identifié dans notre CRM
    # (client/locataire/lead), on lui fait confiance et on bypass les
    # filtres anti-spam. Sinon un locataire qui appelle plusieurs fois
    # en urgence se ferait bannir.
    verstat = params.get("StirVerstat") or params.get("VerStat") or None
    if identified.kind != CallerKind.UNKNOWN:
        spam = None  # type: ignore[assignment]
    else:
        spam = await check_incoming(db, from_e164=from_e164, verstat=verstat)
    if spam is not None and spam.result != SpamCheckResult.ALLOW:
        existing.was_blocked = True
        existing.intent = "spam"
        await record_spam_block(db)
        await db.flush()
        log.info(
            "Spam blocked from=%s reason=%s (%s)",
            from_e164, spam.result.value, spam.reason,
        )
        if spam.result == SpamCheckResult.BLOCK_CAP:
            # Cost cap atteint : on garde le canal ouvert mais on
            # bascule sur voicemail (au cas où c'est un vrai client).
            twiml = provider.build_voicemail(
                intro_say=(
                    "Bonjour, vous avez joint Horizon Services Immobiliers. "
                    "Laissez votre message après le bip, nous vous "
                    "rappellerons dès que possible."
                ),
                lang="fr-CA",
                action_url=_voicemail_action_url(),
                transcribe_callback_url=_voicemail_transcribe_url(),
            )
            return Response(content=twiml, media_type="application/xml")
        # Tous les autres motifs : raccrochage poli (Reject = tonalité
        # occupé, le robot ne saura pas qu'on l'a démasqué).
        twiml = provider.build_reject_response("busy")
        return Response(content=twiml, media_type="application/xml")

    # ----- Routage Phase 3 : blocklist / VIP / heures / secrétaire -----
    action = await decide_routing(
        db,
        phone_number_id=pn.id,
        from_e164=from_e164,
        secretary_mode_active=pn.secretary_mode_active,
    )

    if action == RoutingAction.BLOCK:
        existing.was_blocked = True
        existing.intent = "spam"
        await db.flush()
        twiml = provider.build_reject_response("busy")
        return Response(content=twiml, media_type="application/xml")

    if action == RoutingAction.VIP:
        existing.was_vip = True
        await db.flush()
        if not forward_to:
            twiml = provider.build_say_and_hangup(
                say="Bonjour, merci de votre appel. Au revoir.",
                lang="fr-CA",
            )
            return Response(content=twiml, media_type="application/xml")
        # VIP : on sonne sans secrétaire, même si secretary_mode_active.
        twiml = provider.build_forward_response(forward_to_e164=forward_to)
        return Response(content=twiml, media_type="application/xml")

    if action == RoutingAction.VOICEMAIL:
        existing.was_voicemail = True
        await db.flush()
        twiml = provider.build_voicemail(
            intro_say=(
                "Bonjour, vous avez joint Horizon Services Immobiliers. "
                "Nos bureaux sont actuellement fermés. Laissez votre nom, "
                "votre numéro et la raison de votre appel après le bip, "
                "nous vous rappellerons dès que possible."
            ),
            lang="fr-CA",
            action_url=_voicemail_action_url(),
            transcribe_callback_url=_voicemail_transcribe_url(),
        )
        return Response(content=twiml, media_type="application/xml")

    if action == RoutingAction.SECRETARY:
        # Tour 0 : phrase d'accueil + Gather du 1er énoncé client.
        # Si l'appelant est identifié, on personnalise le greeting.
        personalized = (
            build_personalized_greeting(identified)
            if identified.kind != CallerKind.UNKNOWN
            else None
        )
        greeting = await decide_initial_greeting(
            lang="fr-CA", personalized_say=personalized
        )
        existing.lang = greeting.lang
        await _record_turn(
            db, call_id=existing.id, role="assistant", text=greeting.say
        )
        twiml = provider.build_say_and_gather(
            say=greeting.say,
            lang=greeting.lang,
            action_url=_secretary_action_url(),
        )
        return Response(content=twiml, media_type="application/xml")

    # ----- FORWARD (Phase 1) : transfert direct -----
    if not forward_to:
        twiml = provider.build_say_and_hangup(
            say="Bonjour, nous vous rappellerons sous peu. Merci.",
            lang="fr-CA",
        )
        return Response(content=twiml, media_type="application/xml")

    twiml = provider.build_forward_response(forward_to_e164=forward_to)
    return Response(content=twiml, media_type="application/xml")


# ---------------------------------------------------------------------
# Webhook : tour de conversation avec la secrétaire IA
# ---------------------------------------------------------------------


@router.post(
    "/twilio/secretary",
    summary="Webhook Twilio : tour de la secrétaire IA",
    response_class=Response,
)
async def twilio_secretary_turn(request: Request, db: DBSession) -> Response:
    try:
        return await _twilio_secretary_turn_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_secretary_turn failed")
        return _safe_error_twiml()


async def _twilio_secretary_turn_impl(request: Request, db: DBSession) -> Response:
    """Reçoit la transcription du tour de l'appelant + renvoie le TwiML
    suivant (continue / transfer / callback / end_spam)."""
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()

    call_sid = params.get("CallSid", "")
    if not call_sid:
        raise HTTPException(status_code=400, detail="Missing CallSid")

    call = (
        await db.execute(select(Call).where(Call.provider_sid == call_sid))
    ).scalar_one_or_none()
    if call is None:
        # Cas extrême : Twilio rappelle /secretary sans qu'on ait la ligne.
        # On répond proprement plutôt que 500 (qui ferait rejouer le hook).
        twiml = provider.build_say_and_hangup(
            say="Désolée, une erreur est survenue. Au revoir.",
            lang="fr-CA",
        )
        return Response(content=twiml, media_type="application/xml")

    speech_result = (params.get("SpeechResult") or "").strip()
    confidence_raw = params.get("Confidence")
    confidence = None
    try:
        if confidence_raw:
            confidence = float(confidence_raw)
    except ValueError:
        confidence = None

    if speech_result:
        await _record_turn(
            db,
            call_id=call.id,
            role="user",
            text=speech_result,
            confidence=confidence,
        )

    # Recharge tous les tours pour avoir l'historique complet (l'IA
    # décide en fonction du contexte).
    turns = (
        await db.execute(
            select(CallTurn)
            .where(CallTurn.call_id == call.id)
            .order_by(CallTurn.turn_index)
        )
    ).scalars().all()
    history = [(t.role, t.text) for t in turns]

    # Re-identifie l'appelant pour passer le contexte à Claude (rapide :
    # comparaison SQL sur 10 derniers chiffres, indexée).
    identified = await identify_caller(db, call.from_e164)
    identity_ctx = (
        build_identity_context_block(identified)
        if identified.kind != CallerKind.UNKNOWN
        else None
    )
    decision = await decide_next_turn(
        history=history,
        current_turn_count=len(turns),
        caller_e164=call.from_e164,
        identity_context=identity_ctx,
    )

    # Persist langue + intent à mesure (la dernière décision écrase).
    call.lang = decision.lang
    if decision.intent and decision.intent != "unclear":
        call.intent = decision.intent
    if decision.lead_name:
        call.lead_name = decision.lead_name[:255]
    if decision.lead_callback_phone:
        call.lead_callback_phone = decision.lead_callback_phone[:50]
    if decision.lead_reason:
        call.lead_reason = decision.lead_reason

    await _record_turn(
        db, call_id=call.id, role="assistant", text=decision.say
    )

    # ─── Routage spécialisé Phase 8 ───
    #
    # 1) Urgence locataire : on transfère TOUT DE SUITE vers le numéro
    #    gestionnaire (env URGENCY_FORWARD_E164, sinon TWILIO_FORWARD_TO
    #    en dernier recours pour ne jamais raccrocher un cas urgent).
    if decision.next_action == "transfer_emergency":
        # Récupère les numéros d'urgence du PhoneNumber (peut être
        # une liste séparée par virgules pour ring plusieurs cibles
        # en parallèle). Fallback env vars URGENCY_FORWARD_E164 +
        # TWILIO_FORWARD_TO.
        _pn_for_urgence = (
            await db.execute(
                select(PhoneNumber).where(
                    PhoneNumber.id == call.phone_number_id
                )
            )
        ).scalar_one_or_none()
        # Priorité au contact d'urgence de l'immeuble du locataire ; à
        # défaut, repli sur le numéro de garde global (PhoneNumber / env).
        imm_urgence = await _immeuble_urgence_phone_for_call(db, call)
        if imm_urgence:
            targets = _parse_e164_list(imm_urgence)
        else:
            targets = _parse_e164_list(
                (
                    _pn_for_urgence.urgency_forward_e164
                    if _pn_for_urgence
                    else None
                )
                or os.getenv("URGENCY_FORWARD_E164")
                or os.getenv("TWILIO_FORWARD_TO")
                or ""
            )
        # Notif cloche urgente — TOUS les owners reçoivent pour qu'au
        # moins une personne soit avertie même si la cible ne décroche pas.
        await _notify_owners_urgence(
            db,
            call=call,
            reason=decision.lead_reason or "Urgence détectée",
        )
        if not targets:
            # Pas de cible configurée → on ne raccroche pas sec : on
            # capture en callback urgent pour rappel manuel.
            call.intent = "urgence_locataire"
            call.lead_reason = (
                (decision.lead_reason or "") + " [URGENCE LOCATAIRE]"
            ).strip()
            await _create_lead_from_callback(db, call=call)
            twiml = provider.build_say_and_hangup(
                say=decision.say, lang=decision.lang
            )
            return Response(content=twiml, media_type="application/xml")
        call.forwarded_to_e164 = ",".join(targets)
        call.intent = "urgence_locataire"
        # Tâche d'entreprise pour tracer/suivre l'urgence locataire
        # (l'IA route vers la bonne entreprise). Fire-and-forget : ne
        # casse jamais l'appel en cours.
        try:
            from app.integrations.voice.lea_task import create_task_from_call

            await create_task_from_call(
                db,
                reason=decision.lead_reason or "Urgence locataire signalée",
                caller_name=decision.lead_name,
                caller_phone=decision.lead_callback_phone,
                intent="urgence locataire",
            )
        except Exception:  # noqa: BLE001
            pass
        # Multi-cible : premier qui décroche prend l'appel, les autres
        # cessent. Enregistrement audio activé (consentement annoncé
        # par Léa juste avant). Fallback callback si personne décroche.
        action_url = (
            f"{_secretary_base_url()}/api/v1/voice/twilio/"
            f"dial-followup?call_id={call.id}"
        )
        # Préfixe d'annonce de consentement enregistrement (Loi 25).
        say_with_consent = (
            decision.say
            + " Cet appel pourrait être enregistré pour fins de qualité."
        )
        twiml = provider.build_say_and_dial_multi(
            say=say_with_consent,
            lang=decision.lang,
            targets_e164=targets,
            action_url=action_url,
            timeout_sec=20,
            record=True,
        )
        return Response(content=twiml, media_type="application/xml")

    # 2) Suivi projet : on essaye d'abord de joindre les membres
    #    online du projet via Voice SDK (browser ringing — gratuit),
    #    sinon fallback mobile.
    if decision.next_action == "transfer_project_lead":
        project_lead_to = await _find_project_lead_phone(
            db, call=call
        )
        if voice_sdk_configured():
            online_uids = await _find_project_lead_online_user_ids(
                db, call=call
            )
            if online_uids:
                clients_xml = build_dial_clients_xml(online_uids, parent_call_sid=call.provider_sid)
                fallback_url = (
                    f"{_secretary_base_url()}/api/v1/voice/twilio/"
                    f"clients-fallback?call_id={call.id}"
                )
                call.intent = "suivi_projet"
                call.forwarded_to_e164 = project_lead_to or None
                twiml = provider.build_say_dial_clients_then_mobile(
                    say=decision.say,
                    lang=decision.lang,
                    clients_xml=clients_xml,
                    fallback_action_url=fallback_url,
                    timeout_sec=15,
                )
                return Response(content=twiml, media_type="application/xml")
        if project_lead_to:
            call.forwarded_to_e164 = project_lead_to
            call.intent = "suivi_projet"
            twiml = provider.build_say_and_dial(
                say=decision.say,
                lang=decision.lang,
                dial_to_e164=project_lead_to,
            )
            return Response(content=twiml, media_type="application/xml")
        # Personne disponible → callback poli (le chargé sera notifié
        # via la fiche projet → onglet Communications).
        call.intent = "suivi_projet"
        await _create_lead_from_callback(db, call=call)
        twiml = provider.build_say_and_hangup(
            say=decision.say, lang=decision.lang
        )
        return Response(content=twiml, media_type="application/xml")

    # 3) Intake construction terminé : on persiste la collecte de Léa
    #    dans un ContactRequest avec un token de validation, on envoie
    #    le courriel récap, puis on raccroche poliment.
    if decision.next_action == "intake_complete":
        cr_id = await _create_intake_contact_request(
            db, call=call, intake_data=decision.intake_data
        )
        call.intent = "intake_construction"
        call.contact_request_id = cr_id
        # Tâche de suivi pour l'équipe (l'IA route vers la bonne
        # entreprise). Fire-and-forget : ne bloque/casse jamais l'appel.
        try:
            from app.integrations.voice.lea_task import create_task_from_call

            await create_task_from_call(
                db,
                reason=decision.lead_reason or decision.say,
                caller_name=decision.lead_name,
                caller_phone=decision.lead_callback_phone,
                intent="intake construction",
            )
        except Exception:  # noqa: BLE001
            pass
        twiml = provider.build_say_and_hangup(
            say=decision.say, lang=decision.lang
        )
        return Response(content=twiml, media_type="application/xml")

    # 4) Smart booking — Léa cherche 3 créneaux libres pour un closer
    #    et les annonce à l'appelant. On stocke les créneaux proposés
    #    dans intake_data['proposed_slots'] pour retrouver à
    #    chosen_slot_index quand l'appelant choisira au tour suivant.
    if decision.next_action == "propose_slots":
        proposed = await _propose_appointment_slots(
            db, call=call, intake_data=decision.intake_data
        )
        if not proposed:
            # Aucun closer disponible cette semaine → on retombe sur
            # intake_complete (callback humain).
            cr_id = await _create_intake_contact_request(
                db, call=call, intake_data=decision.intake_data
            )
            call.intent = "intake_construction"
            call.contact_request_id = cr_id
            fallback = (
                "Désolée, aucune disponibilité cette semaine. Nous "
                "vous rappellerons sous peu pour fixer un rendez-vous."
                if decision.lang.startswith("fr")
                else "Sorry, no availability this week. We'll call you "
                "back shortly to schedule a visit."
            )
            twiml = provider.build_say_and_hangup(
                say=fallback, lang=decision.lang
            )
            return Response(content=twiml, media_type="application/xml")
        announcement = _format_slots_announcement(proposed, lang=decision.lang)
        # IMPORTANT : on remplace le tour assistant déjà enregistré
        # (qui contient le `say` brut de Léa) par l'annonce détaillée
        # avec les 3 slots énumérés. Permet à Léa de retrouver
        # « 1) jeudi 14h » dans l'historique au tour suivant.
        await _record_turn(
            db, call_id=call.id, role="assistant", text=announcement
        )
        twiml = provider.build_say_and_gather(
            say=announcement,
            lang=decision.lang,
            action_url=_secretary_action_url(),
        )
        return Response(content=twiml, media_type="application/xml")

    # 5) Smart booking — l'appelant a choisi un des créneaux proposés.
    if decision.next_action == "book_slot":
        idx = decision.chosen_slot_index
        # Récupère les slots proposés depuis session_state (persistés
        # au tour précédent par _propose_appointment_slots).
        state = {}
        if call.session_state:
            try:
                state = json.loads(call.session_state) or {}
            except Exception:
                state = {}
        proposed_serialized = state.get("proposed_slots") or []
        intake = state.get("intake_data") or decision.intake_data or {}
        if not proposed_serialized or idx is None:
            cr_id = await _create_intake_contact_request(
                db, call=call, intake_data=intake
            )
            call.intent = "intake_construction"
            call.contact_request_id = cr_id
            twiml = provider.build_say_and_hangup(
                say=decision.say, lang=decision.lang
            )
            return Response(content=twiml, media_type="application/xml")
        # Injecte les proposed_slots dans l'intake pour _book_chosen_slot
        intake_for_book = dict(intake)
        intake_for_book["proposed_slots"] = proposed_serialized
        booked = await _book_chosen_slot(
            db,
            call=call,
            intake_data=intake_for_book,
            chosen_index=idx,
        )
        if not booked:
            twiml = provider.build_say_and_hangup(
                say=(
                    "Ce créneau n'est plus disponible, nous vous "
                    "rappellerons. Merci !"
                    if decision.lang.startswith("fr")
                    else "That slot is no longer available, we'll call "
                    "you back. Thanks!"
                ),
                lang=decision.lang,
            )
            return Response(content=twiml, media_type="application/xml")
        twiml = provider.build_say_and_hangup(
            say=decision.say, lang=decision.lang
        )
        return Response(content=twiml, media_type="application/xml")

    # Branche selon l'action décidée.
    if decision.next_action == "transfer":
        # Re-query PhoneNumber explicitement (async SQLAlchemy ne
        # supporte pas le lazy-load `call.phone_number` ici).
        pn = (
            await db.execute(
                select(PhoneNumber).where(PhoneNumber.id == call.phone_number_id)
            )
        ).scalar_one_or_none()
        forward_to = (
            (pn.forward_to_e164 if pn else None)
            or os.getenv("TWILIO_FORWARD_TO")
            or ""
        ).strip()

        # Voice SDK hybride : si des users sont online dans le portail,
        # on les ring d'abord via WebRTC (gratuit). Fallback mobile
        # après 15 sec via /twilio/clients-fallback.
        if voice_sdk_configured():
            online_uids = await list_online_user_ids(db)
            if online_uids:
                call.forwarded_to_e164 = forward_to or None
                clients_xml = build_dial_clients_xml(online_uids, parent_call_sid=call.provider_sid)
                fallback_url = (
                    f"{_secretary_base_url()}/api/v1/voice/twilio/"
                    f"clients-fallback?call_id={call.id}"
                )
                twiml = provider.build_say_dial_clients_then_mobile(
                    say=decision.say,
                    lang=decision.lang,
                    clients_xml=clients_xml,
                    fallback_action_url=fallback_url,
                    timeout_sec=15,
                )
                return Response(content=twiml, media_type="application/xml")

        if not forward_to:
            # Pas de cible de transfert ni de client online → callback.
            await _create_lead_from_callback(db, call=call)
            twiml = provider.build_say_and_hangup(
                say=decision.say, lang=decision.lang
            )
            return Response(content=twiml, media_type="application/xml")
        # Multi-cible : si le champ contient plusieurs numéros séparés
        # par virgule, on ring tout le monde en parallèle. Fallback
        # callback si personne ne décroche. Enregistrement activé +
        # consentement annoncé.
        targets = _parse_e164_list(forward_to)
        call.forwarded_to_e164 = ",".join(targets) if targets else forward_to
        action_url = (
            f"{_secretary_base_url()}/api/v1/voice/twilio/"
            f"dial-followup?call_id={call.id}"
        )
        say_with_consent = (
            decision.say
            + " Cet appel pourrait être enregistré pour fins de qualité."
        )
        twiml = provider.build_say_and_dial_multi(
            say=say_with_consent,
            lang=decision.lang,
            targets_e164=targets or [forward_to],
            action_url=action_url,
            timeout_sec=20,
            record=True,
        )
        return Response(content=twiml, media_type="application/xml")

    if decision.next_action == "callback":
        await _create_lead_from_callback(db, call=call)
        twiml = provider.build_say_and_hangup(
            say=decision.say, lang=decision.lang
        )
        return Response(content=twiml, media_type="application/xml")

    if decision.next_action == "end_spam":
        twiml = provider.build_say_and_hangup(
            say=decision.say, lang=decision.lang
        )
        return Response(content=twiml, media_type="application/xml")

    # next_action == 'continue' → on relance un <Gather>.
    twiml = provider.build_say_and_gather(
        say=decision.say,
        lang=decision.lang,
        action_url=_secretary_action_url(),
    )
    return Response(content=twiml, media_type="application/xml")


# ---------------------------------------------------------------------
# Webhook : statut de fin d'appel
# ---------------------------------------------------------------------


@router.post(
    "/twilio/status",
    summary="Webhook Twilio : mise à jour de statut (fin d'appel)",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def twilio_call_status(request: Request, db: DBSession) -> Response:
    """Met à jour la ligne `Call` à la fin de l'appel."""
    params = await _validate_twilio_signature(request)

    call_sid = params.get("CallSid", "")
    call_status = params.get("CallStatus", "")
    if not call_sid:
        raise HTTPException(status_code=400, detail="Missing CallSid")

    call = (
        await db.execute(select(Call).where(Call.provider_sid == call_sid))
    ).scalar_one_or_none()
    if call is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if call_status:
        call.status = call_status
    duration_raw = params.get("CallDuration") or params.get("Duration")
    if duration_raw and duration_raw.isdigit():
        call.duration_sec = int(duration_raw)
    if call_status in ("completed", "busy", "no-answer", "failed", "canceled"):
        call.ended_at = datetime.now(timezone.utc)
        if call_status == "completed" and call.answered_at is None and call.duration_sec:
            from datetime import timedelta

            call.answered_at = call.ended_at - timedelta(seconds=call.duration_sec)

    rec_url = params.get("RecordingUrl")
    if rec_url:
        call.recording_url = rec_url
        call.recording_sid = params.get("RecordingSid")
        # Auto-résumé de l'enregistrement (best-effort, en arrière-plan —
        # ne bloque pas la réponse au webhook).
        if not call.recording_summary:
            import asyncio

            from app.services.call_recording_summary import (
                summarize_call_in_background,
            )

            asyncio.create_task(summarize_call_in_background(call.id))

    # Anti-spam : compteurs de coût + honeypot.
    if call_status == "completed" and call.duration_sec:
        try:
            await record_call_cost(
                db,
                duration_sec=call.duration_sec,
                direction=call.direction,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("record_call_cost failed: %s", exc)
        if call.direction == "inbound":
            try:
                await maybe_mark_honeypot(
                    db,
                    from_e164=call.from_e164,
                    duration_sec=call.duration_sec,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("honeypot check failed: %s", exc)

    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------
# Webhook : voicemail (Phase 3)
# ---------------------------------------------------------------------


@router.post(
    "/twilio/voicemail",
    summary="Webhook Twilio : enregistrement de voicemail terminé",
    status_code=status.HTTP_200_OK,
    response_class=Response,
)
async def twilio_voicemail(request: Request, db: DBSession) -> Response:
    try:
        return await _twilio_voicemail_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_voicemail failed")
        return _safe_error_twiml()


async def _twilio_voicemail_impl(request: Request, db: DBSession) -> Response:
    """Twilio appelle ici quand l'enregistrement est terminé.

    On stocke `RecordingUrl` immédiatement (utilisable de suite pour
    écoute). La transcription arrive plus tard via
    `/twilio/voicemail-transcript`. On répond un TwiML de remerciement
    pour finir l'appel proprement.
    """
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()
    call_sid = params.get("CallSid", "")
    if call_sid:
        call = (
            await db.execute(select(Call).where(Call.provider_sid == call_sid))
        ).scalar_one_or_none()
        if call is not None:
            call.was_voicemail = True
            rec_url = params.get("RecordingUrl")
            if rec_url:
                call.recording_url = rec_url
                call.recording_sid = params.get("RecordingSid")
            await db.flush()

    twiml = provider.build_say_and_hangup(
        say="Merci pour votre message. Au revoir.",
        lang="fr-CA",
    )
    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/twilio/voicemail-transcript",
    summary="Webhook Twilio : transcription du voicemail prête",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def twilio_voicemail_transcript(request: Request, db: DBSession) -> Response:
    """Twilio POST le texte transcrit. On le persiste, on génère un
    résumé Claude (best-effort), on crée un ContactRequest CRM et on
    notifie l'admin via la cloche."""
    params = await _validate_twilio_signature(request)
    call_sid = params.get("CallSid", "")
    text = (params.get("TranscriptionText") or "").strip()
    rec_url = params.get("RecordingUrl") or ""

    if not call_sid:
        raise HTTPException(status_code=400, detail="Missing CallSid")

    call = (
        await db.execute(select(Call).where(Call.provider_sid == call_sid))
    ).scalar_one_or_none()
    if call is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    call.voicemail_transcription = text or None
    if rec_url:
        call.recording_url = rec_url

    # Résumé IA — best-effort. Si l'IA tombe, on garde juste la transcription.
    summary: Optional[str] = None
    if text:
        try:
            from app.integrations.ai import chat, Message

            res = await chat(
                messages=[
                    Message(
                        role="user",
                        content=(
                            "Résume ce message vocal laissé sur la boîte "
                            "vocale d'Horizon Services Immobiliers en 1-2 "
                            "phrases courtes, en identifiant l'intent "
                            "(rénovation / logiciel / gestion immo / "
                            "spam / autre) et les coordonnées si "
                            "mentionnées :\n\n"
                            f"{text}"
                        ),
                    )
                ],
                system=(
                    "Tu es un assistant qui résume des messages vocaux. "
                    "Réponds en français québécois, en 2 phrases max. "
                    "Pas de markdown, juste du texte plat."
                ),
                max_tokens=200,
                temperature=0.3,
            )
            summary = res.text.strip() or None
        except Exception as exc:  # noqa: BLE001
            log.warning("Voicemail summary failed: %s", exc)
    call.voicemail_summary = summary

    # Crée un ContactRequest pour que le voicemail apparaisse dans le CRM.
    if text:
        # Réutilise l'helper qui synthétise email/nom depuis le téléphone.
        call.lead_name = call.lead_name or f"Voicemail {call.from_e164}"
        call.lead_callback_phone = call.lead_callback_phone or call.from_e164
        call.lead_reason = summary or text[:500]
        call.intent = call.intent or "callback"
        await _create_lead_from_callback(db, call=call)

    # Notif cloche pour l'owner du numéro (s'il existe), sinon tous les owners.
    try:
        from app.models.notification import Notification
        from app.models.user import User

        pn = (
            await db.execute(
                select(PhoneNumber).where(PhoneNumber.id == call.phone_number_id)
            )
        ).scalar_one_or_none()

        user_ids: list[int] = []
        if pn and pn.owner_user_id:
            user_ids = [pn.owner_user_id]
        else:
            # Fallback : tous les owners (la table est petite).
            owners = (
                await db.execute(select(User.id).where(User.role == "owner"))
            ).scalars().all()
            user_ids = list(owners)

        body = summary or (text[:200] + "…" if len(text) > 200 else text)
        for uid in user_ids:
            db.add(
                Notification(
                    user_id=uid,
                    kind="voicemail_received",
                    title=f"Voicemail de {call.from_e164}",
                    body=body or "Message vocal reçu (transcription vide).",
                    href=f"/telephonie?call={call.id}",
                )
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("Voicemail notification failed: %s", exc)

    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------
# Voice SDK hybride (Phase 4+) — token / presence / dispatch
# ---------------------------------------------------------------------


class VoiceTokenResponse(BaseModel):
    token: str
    identity: str
    ttl_sec: int = 3600


@router.get(
    "/sdk/token",
    response_model=VoiceTokenResponse,
    summary="Twilio Access Token pour le Voice SDK (login user)",
)
async def get_voice_sdk_token(user: CurrentUser) -> VoiceTokenResponse:
    """Le frontend appelle cet endpoint au boot pour s'enregistrer
    comme Twilio Client. Token valide 1h ; le client le re-fetch
    automatiquement à expiration (ou avant en cas de Device error).
    """
    token = generate_access_token(user_id=user.id, ttl_sec=3600)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Voice SDK not configured. Set TWILIO_TWIML_APP_SID, "
                "TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET in env."
            ),
        )
    from app.integrations.voice.voice_sdk import client_identity_for_user

    return VoiceTokenResponse(
        token=token, identity=client_identity_for_user(user.id)
    )


@router.post(
    "/sdk/presence/ping",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Heartbeat de présence (browser ouvert, accepting calls)",
)
async def presence_ping(
    user: CurrentUser,
    db: DBSession,
    accepting: bool = Query(default=True),
) -> Response:
    await update_presence(db, user_id=user.id, accepting=accepting)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class _SDKTranscriptPayload(BaseModel):
    """Verbatim côté navigateur, envoyé à la fin d'un appel."""

    call_sid: Optional[str] = None
    parent_call_sid: Optional[str] = None
    transcript: str


@router.post(
    "/sdk/transcript",
    summary=(
        "Stocke le verbatim Web Speech API d'un appel navigateur "
        "sur la Call correspondante"
    ),
)
async def store_sdk_transcript(
    payload: _SDKTranscriptPayload,
    db: DBSession,
    user: CurrentUser,
) -> dict:
    """Reçoit le transcript collecté par le navigateur pendant
    l'appel (Web Speech API → uniquement notre côté), et l'attache
    à la Call correspondante.

    Stratégie de match :
      1. `parent_call_sid` (passé en custom param TwiML pour les
         appels entrants routés vers le SDK) — préféré.
      2. `call_sid` — la CallSid vue par le SDK ; correspond au
         parent pour les appels sortants, au child pour les entrants.
      3. Aucun match → on logue, on ne crée pas de Call (le
         transcript est perdu côté UI, mais reste dans les logs).
    """
    transcript = (payload.transcript or "").strip()
    if not transcript:
        return {"saved": False, "reason": "empty"}

    candidates: list[str] = []
    if payload.parent_call_sid:
        candidates.append(payload.parent_call_sid.strip())
    if payload.call_sid:
        candidates.append(payload.call_sid.strip())

    call = None
    for sid in candidates:
        if not sid:
            continue
        call = (
            await db.execute(
                select(Call).where(Call.provider_sid == sid)
            )
        ).scalar_one_or_none()
        if call is not None:
            break

    if call is None:
        log.info(
            "SDK transcript non lié (user=%s, sids=%s, len=%d)",
            user.id,
            candidates,
            len(transcript),
        )
        return {"saved": False, "matched": False}

    # Append si on a déjà du verbatim (rare, mais utile pour les
    # appels longs où le navigateur envoie plusieurs paquets).
    existing = call.verbatim_transcript or ""
    if existing:
        call.verbatim_transcript = f"{existing}\n---\n{transcript}"
    else:
        call.verbatim_transcript = transcript
    return {"saved": True, "matched": True, "call_id": call.id}


@router.post(
    "/twilio/sdk-outbound",
    summary="TwiML servi à la TwiML App quand un browser fait device.connect()",
    response_class=Response,
)
async def twilio_sdk_outbound(request: Request) -> Response:
    """Twilio appelle ici quand un user du portail clique un bouton
    « Appeler » qui passe par le Voice SDK (vs notre /calls/outbound
    REST). Le frontend passe `To` dans les params de device.connect().

    On valide la signature, on lit `To`, on renvoie un TwiML qui
    appelle ce numéro avec notre numéro 438 comme callerId.
    """
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()
    to = (params.get("To") or "").strip()
    if not to:
        twiml = provider.build_say_and_hangup(
            say="Numéro manquant. Au revoir.", lang="fr-CA"
        )
        return Response(content=twiml, media_type="application/xml")
    # CallerID = notre numéro principal (1er PhoneNumber actif).
    # `record="record-from-answer-dual"` : Twilio enregistre les
    # deux canaux (notre côté + côté distant) dès que l'appel est
    # décroché — pas durant la sonnerie. Les enregistrements sont
    # visibles dans Twilio Console (Voice → Logs → Recordings) et
    # serviront de base pour la transcription verbatim (étape
    # suivante : callback + service de transcription).
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Dial callerId="{os.getenv("TWILIO_PHONE_NUMBER", "")}" '
        # timeout=40s : laisse le temps à la messagerie vocale du
        # destinataire de décrocher (souvent ~25-30 s) avant que Twilio
        # n'abandonne. À 20 s, notre ligne raccrochait avant la boîte
        # vocale de la cliente.
        'timeout="40" record="record-from-answer-dual">'
        f"{to}"
        "</Dial>"
        "</Response>"
    )
    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/twilio/clients-fallback",
    summary="TwiML de fallback : appelé quand le dispatch <Client> a échoué",
    response_class=Response,
)
async def twilio_clients_fallback(request: Request, db: DBSession) -> Response:
    try:
        return await _twilio_clients_fallback_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_clients_fallback failed")
        return _safe_error_twiml()


async def _twilio_clients_fallback_impl(request: Request, db: DBSession) -> Response:
    """Twilio appelle ici si :
    - aucun Client n'a répondu dans le timeout (15 sec)
    - tous les Clients ont décliné
    - erreur réseau côté browser

    On bascule sur le numéro mobile fallback (forward_to_e164 ou
    TWILIO_FORWARD_TO). Si pas non plus configuré → voicemail.
    """
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()
    call_id_raw = request.query_params.get("call_id", "")
    dial_status = (params.get("DialCallStatus") or "").lower()

    # Si le Dial a réussi (answered/completed), Twilio ne va PAS rejouer
    # le flow — il vient juste nous notifier. On répond vide.
    if dial_status in ("answered", "completed"):
        return Response(content="<Response/>", media_type="application/xml")

    forward_to = ""
    if call_id_raw.isdigit():
        call = (
            await db.execute(select(Call).where(Call.id == int(call_id_raw)))
        ).scalar_one_or_none()
        if call is not None:
            forward_to = (call.forwarded_to_e164 or "").strip()

    if not forward_to:
        forward_to = (os.getenv("TWILIO_FORWARD_TO") or "").strip()

    if not forward_to:
        twiml = provider.build_voicemail(
            intro_say=(
                "Désolée, personne n'est disponible pour l'instant. "
                "Laissez votre message après le bip."
            ),
            lang="fr-CA",
            action_url=_voicemail_action_url(),
            transcribe_callback_url=_voicemail_transcribe_url(),
        )
        return Response(content=twiml, media_type="application/xml")

    twiml = provider.build_forward_response(forward_to_e164=forward_to)
    return Response(content=twiml, media_type="application/xml")


# ---------------------------------------------------------------------
# Multi-target dial : callback de résultat
# ---------------------------------------------------------------------
#
# Quand Léa <Dial> plusieurs numéros en parallèle (urgence locataire,
# transfer générique, etc.), Twilio POST ici à la fin du Dial avec :
#   - DialCallStatus : answered / completed / no-answer / busy / failed
#   - DialCallSid    : SID du leg appelé qui a répondu (si answered)
#   - RecordingUrl   : URL de l'enregistrement (si record=True)
#
# Si quelqu'un a répondu  → on notifie les autres « pris en charge »
# Si personne n'a répondu → Léa dit qu'on rappelle ASAP + push urgent


@router.post(
    "/twilio/dial-followup",
    summary="Post-dial multi-cible : notifie les autres OU bascule en callback",
    response_class=Response,
)
async def twilio_dial_followup(
    request: Request, db: DBSession
) -> Response:
    try:
        return await _twilio_dial_followup_impl(request, db)
    except HTTPException as _http_exc:
        log.warning(
            "dial-followup rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_dial_followup failed")
        return _safe_error_twiml()


async def _twilio_dial_followup_impl(
    request: Request, db: DBSession
) -> Response:
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()
    call_id_raw = request.query_params.get("call_id", "")
    dial_status = (params.get("DialCallStatus") or "").lower()
    answered_by = (params.get("DialCallSid") or "").strip()
    duration_raw = params.get("DialCallDuration") or "0"
    recording_url = (params.get("RecordingUrl") or "").strip()

    call = None
    if call_id_raw.isdigit():
        call = (
            await db.execute(select(Call).where(Call.id == int(call_id_raw)))
        ).scalar_one_or_none()

    # Persist le recording URL sur l'appel parent (sera transcrit
    # asynchrone par le webhook /twilio/voicemail-transcript si on
    # branche un transcribe-callback).
    if call is not None and recording_url:
        call.recording_url = recording_url
        await db.flush()

    # SUCCÈS : quelqu'un a répondu → notifie tous les owners « pris
    # en charge » pour éviter que d'autres rappellent inutilement.
    if dial_status in ("answered", "completed"):
        if call is not None:
            await _notify_call_taken(db, call=call, duration_sec=int(duration_raw) if duration_raw.isdigit() else None)
        # On ne renvoie pas de TwiML supplémentaire — la conversation
        # est en cours côté humain.
        return Response(content="<Response/>", media_type="application/xml")

    # ÉCHEC : personne n'a décroché → message d'excuse + callback
    # + push urgent à tous les owners pour rappel manuel ASAP.
    if call is not None:
        if call.intent != "urgence_locataire":
            call.intent = call.intent or "callback"
        call.lead_reason = (
            (call.lead_reason or "") + " [NO ANSWER - RAPPEL REQUIS]"
        ).strip()
        await _create_lead_from_callback(db, call=call)
        await _notify_callback_required(db, call=call)

    lang = (call.lang if call else "fr-CA") or "fr-CA"
    say = (
        "Désolée, personne ne peut prendre votre appel pour l'instant. "
        "Nous vous rappellerons le plus rapidement possible. Merci !"
        if lang.startswith("fr")
        else "Sorry, nobody can take your call right now. We will call "
        "you back as soon as possible. Thank you!"
    )
    twiml = provider.build_say_and_hangup(say=say, lang=lang)
    return Response(content=twiml, media_type="application/xml")


async def _notify_call_taken(
    db, *, call: "Call", duration_sec: Optional[int]
) -> None:
    """Quand un appel multi-cible a été pris par quelqu'un, on push
    aux autres owners pour leur dire « inutile de rappeler »."""
    try:
        from app.integrations.webpush import push_to_users
        from app.models.notification import Notification
        from app.models.user import User

        owners = (
            await db.execute(
                select(User.id).where(User.role.in_(("owner", "admin")))
            )
        ).scalars().all()
        dur_str = f" ({duration_sec}s)" if duration_sec else ""
        title = f"✅ Appel pris en charge — {call.from_e164}"
        body = (
            f"L'appel a été répondu{dur_str}. Aucun rappel nécessaire."
        )
        href = f"/telephonie?call={call.id}"
        for uid in owners:
            db.add(
                Notification(
                    user_id=uid,
                    kind="call_handled",
                    title=title,
                    body=body,
                    href=href,
                )
            )
        await db.flush()
        try:
            await push_to_users(
                db,
                user_ids=list(owners),
                title=title,
                body=body,
                href=href,
                tag=f"handled-{call.id}",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("call_handled push failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("_notify_call_taken failed: %s", exc)


async def _notify_callback_required(db, *, call: "Call") -> None:
    """Quand personne n'a décroché un transfert, on push à tous les
    owners pour rappel manuel rapide. URGENT pour les urgences."""
    try:
        from app.integrations.webpush import push_to_users
        from app.models.notification import Notification
        from app.models.user import User

        owners = (
            await db.execute(
                select(User.id).where(User.role.in_(("owner", "admin")))
            )
        ).scalars().all()
        is_urgent = call.intent == "urgence_locataire"
        title = (
            f"🚨 RAPPEL URGENT — {call.from_e164}"
            if is_urgent
            else f"📞 Rappel à faire — {call.from_e164}"
        )
        body = (
            f"Aucun de tes contacts n'a décroché. Rappel manuel requis. "
            f"{call.lead_reason or ''}"
        )[:500]
        href = f"/telephonie?call={call.id}"
        for uid in owners:
            db.add(
                Notification(
                    user_id=uid,
                    kind="callback_required",
                    title=title,
                    body=body,
                    href=href,
                )
            )
        await db.flush()
        try:
            await push_to_users(
                db,
                user_ids=list(owners),
                title=title,
                body=body,
                href=href,
                tag=f"callback-{call.id}",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("callback_required push failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("_notify_callback_required failed: %s", exc)


# ---------------------------------------------------------------------
# Sortant + lien CRM (Phase 4)
# ---------------------------------------------------------------------


class OutboundCallRequest(BaseModel):
    target_e164: str = Field(min_length=4, max_length=20)
    entity_type: Optional[str] = Field(default=None, max_length=32)
    entity_id: Optional[int] = None
    # Si non fourni, on prend le 1er PhoneNumber actif comme caller ID.
    from_phone_number_id: Optional[int] = None


class OutboundCallResponse(BaseModel):
    call_id: int
    provider_sid: str
    bridge_to_e164: str
    target_e164: str


@router.post(
    "/calls/outbound",
    response_model=OutboundCallResponse,
    summary="Initie un appel sortant click-to-call (admin)",
)
async def create_outbound_call(
    payload: OutboundCallRequest, _: CurrentAdmin, db: DBSession
) -> OutboundCallResponse:
    """Click-to-call : Twilio appelle d'abord le mobile interne
    (`TWILIO_FORWARD_TO`), puis bridge vers la cible une fois qu'on a
    décroché. Crée la ligne `Call` AVANT l'API call pour pouvoir
    référencer `call_id` dans l'URL du bridge TwiML.
    """
    target = _normalize_e164(payload.target_e164)
    if not target.startswith("+"):
        raise HTTPException(status_code=400, detail="target must be E.164 (+...)")
    if payload.entity_type and payload.entity_type not in SUPPORTED_ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="unsupported entity_type")

    # PhoneNumber source : explicite ou le 1er actif.
    if payload.from_phone_number_id:
        pn = (
            await db.execute(
                select(PhoneNumber).where(
                    PhoneNumber.id == payload.from_phone_number_id,
                    PhoneNumber.active.is_(True),
                )
            )
        ).scalar_one_or_none()
    else:
        pn = (
            await db.execute(
                select(PhoneNumber)
                .where(PhoneNumber.active.is_(True))
                .order_by(PhoneNumber.id)
                .limit(1)
            )
        ).scalar_one_or_none()
    if pn is None:
        raise HTTPException(status_code=400, detail="no_active_phone_number")

    bridge_to = (
        (pn.forward_to_e164 or os.getenv("TWILIO_FORWARD_TO") or "").strip()
    )
    if not bridge_to:
        raise HTTPException(
            status_code=400,
            detail="no_bridge_target (set forward_to_e164 or TWILIO_FORWARD_TO)",
        )

    # On crée la ligne d'abord pour avoir l'ID dispo dans l'URL TwiML.
    call = Call(
        phone_number_id=pn.id,
        # Sera remplacé par le vrai CallSid juste après.
        provider_sid=f"pending-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        direction=CallDirection.OUTBOUND.value,
        status=CallStatus.QUEUED.value,
        from_e164=pn.e164,
        to_e164=target,
        forwarded_to_e164=bridge_to,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        lang="fr-CA",
    )
    db.add(call)
    await db.flush()

    provider = _twilio_provider()
    base_status_url = f"{_secretary_base_url()}/api/v1/voice/twilio/status"
    try:
        sid = await provider.initiate_outbound_call(
            from_e164=pn.e164,
            to_e164=bridge_to,
            twiml_url=_outbound_bridge_url(call.id),
            status_callback_url=base_status_url,
        )
    except Exception as exc:
        # Rollback la ligne pour ne pas garder une row orpheline.
        await db.delete(call)
        await db.flush()
        log.exception("Outbound call initiation failed")
        raise HTTPException(status_code=502, detail=f"twilio_error: {exc}")

    call.provider_sid = sid or call.provider_sid
    await db.flush()

    return OutboundCallResponse(
        call_id=call.id,
        provider_sid=call.provider_sid,
        bridge_to_e164=bridge_to,
        target_e164=target,
    )


@router.post(
    "/twilio/lead-outbound",
    summary="Webhook Twilio : conversation IA outbound (qualification lead)",
    response_class=Response,
)
async def twilio_lead_outbound(request: Request, db: DBSession) -> Response:
    try:
        return await _twilio_lead_outbound_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_lead_outbound failed")
        return _safe_error_twiml()


async def _twilio_lead_outbound_impl(request: Request, db: DBSession) -> Response:
    """Drive la conversation IA sortante de qualification d'un lead.

    Premier appel (sans turns) : greeting personnalisé + Gather du
    premier énoncé du lead. Tours suivants : on alimente Claude avec
    l'historique + le contexte ContactRequest, on persiste la réponse,
    et on dispatch selon `next_action` (rdv_*, callback, lost, etc.).

    À la fin : on met à jour la fiche ContactRequest (status='contacted',
    kanban_column, internal_notes avec le résumé IA).
    """
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()

    call_id_raw = request.query_params.get("call_id", "")
    call_id = int(call_id_raw) if call_id_raw.isdigit() else 0
    if not call_id:
        twiml = provider.build_say_and_hangup(
            say="Désolée, une erreur est survenue. Au revoir.",
            lang="fr-CA",
        )
        return Response(content=twiml, media_type="application/xml")

    call = (
        await db.execute(select(Call).where(Call.id == call_id))
    ).scalar_one_or_none()
    if call is None:
        twiml = provider.build_say_and_hangup(
            say="Désolée, une erreur est survenue. Au revoir.",
            lang="fr-CA",
        )
        return Response(content=twiml, media_type="application/xml")

    # Met à jour le CallSid si on le voit pour la 1re fois.
    sid = params.get("CallSid", "")
    if sid and not call.provider_sid.startswith("CA"):
        call.provider_sid = sid

    cr = None
    if call.entity_type == "contact_request" and call.entity_id:
        cr = (
            await db.execute(
                select(ContactRequest).where(ContactRequest.id == call.entity_id)
            )
        ).scalar_one_or_none()

    speech_result = (params.get("SpeechResult") or "").strip()
    confidence_raw = params.get("Confidence")
    confidence = None
    try:
        if confidence_raw:
            confidence = float(confidence_raw)
    except ValueError:
        pass

    if speech_result:
        await _record_turn(
            db, call_id=call.id, role="user", text=speech_result,
            confidence=confidence,
        )

    turns = (
        await db.execute(
            select(CallTurn)
            .where(CallTurn.call_id == call.id)
            .order_by(CallTurn.turn_index)
        )
    ).scalars().all()

    # Tour 0 — greeting personnalisé.
    if not turns and cr is not None:
        greeting = _build_outbound_greeting(cr)
        call.lang = greeting.lang
        await _record_turn(
            db, call_id=call.id, role="assistant", text=greeting.say
        )
        twiml = provider.build_say_and_gather(
            say=greeting.say,
            lang=greeting.lang,
            action_url=f"{_secretary_base_url()}/api/v1/voice/twilio/lead-outbound?call_id={call.id}",
        )
        return Response(content=twiml, media_type="application/xml")

    # Tours suivants — pilotage Claude.
    if cr is None:
        # Cas dégénéré : pas de contexte → on raccroche poliment.
        twiml = provider.build_say_and_hangup(
            say="Merci pour votre appel. Au revoir.", lang=call.lang or "fr-CA"
        )
        return Response(content=twiml, media_type="application/xml")

    system_prompt = build_outbound_system_prompt(
        lead_name=cr.name,
        project_type=cr.project_type,
        message=cr.message or "",
        budget_range=cr.budget_range,
        address=cr.address,
        lang=call.lang or "fr-CA",
    )
    history = [(t.role, t.text) for t in turns]
    decision = await decide_lead_outbound_turn(
        history=history,
        system_prompt=system_prompt,
        turn_count=len(turns),
    )

    call.lang = decision.lang
    if decision.summary:
        call.lead_reason = decision.summary
    await _record_turn(
        db, call_id=call.id, role="assistant", text=decision.say
    )

    # Dispatch final.
    if decision.next_action == "continue":
        twiml = provider.build_say_and_gather(
            say=decision.say,
            lang=decision.lang,
            action_url=f"{_secretary_base_url()}/api/v1/voice/twilio/lead-outbound?call_id={call.id}",
        )
        return Response(content=twiml, media_type="application/xml")

    # Persistance finale dans la fiche CRM.
    await _commit_lead_outcome(
        db, cr=cr, call=call, decision=decision,
    )

    twiml = provider.build_say_and_hangup(say=decision.say, lang=decision.lang)
    return Response(content=twiml, media_type="application/xml")


def _build_outbound_greeting(cr: ContactRequest) -> "type('G', (), {})":  # type: ignore[valid-type]
    """Greeting statique court qui mentionne le contexte du lead."""
    lang = "en-US" if (cr.locale or "fr").startswith("en") else "fr-CA"
    project_fr = {
        "salle_bain": "salle de bain",
        "cuisine": "cuisine",
        "multilogement": "multilogement",
        "renovation_complete": "rénovation complète",
    }.get(cr.project_type, "rénovation")

    first_name = (cr.name or "").split(" ")[0] if cr.name else ""
    if lang.startswith("en"):
        say = (
            f"Hello{' ' + first_name if first_name else ''}, this is Léa from "
            f"Horizon Services Immobiliers. I'm calling about the {cr.project_type} "
            "request you just submitted on our website. Is now a good time?"
        )
    else:
        say = (
            f"Bonjour{' ' + first_name if first_name else ''}, c'est Léa "
            f"d'Horizon Services Immobiliers. Je vous appelle suite à "
            f"votre demande pour {project_fr} sur notre site. "
            "Vous avez 2 minutes pour qu'on en parle ?"
        )

    # Wrap in a small object compat avec ce que la fonction appelante attend.
    class _G:
        pass
    g = _G()
    g.lang = lang
    g.say = say
    return g  # type: ignore[return-value]


async def _commit_lead_outcome(
    db,
    *,
    cr: ContactRequest,
    call: Call,
    decision,
) -> None:
    """Met à jour ContactRequest selon le résultat de l'appel IA outbound
    + crée un AgendaEvent si RDV demandé."""
    from app.models.contact_request import ContactRequestStatus as _CRS

    cr.status = _CRS.CONTACTED.value
    bits: list[str] = []
    if decision.summary:
        bits.append(decision.summary)
    if decision.qualified_budget:
        bits.append(f"Budget : {decision.qualified_budget}")
    if decision.qualified_timeline:
        bits.append(f"Échéancier : {decision.qualified_timeline}")
    if decision.callback_when:
        bits.append(f"Rappel demandé : {decision.callback_when}")
    summary_text = " — ".join(bits) or "Appel IA effectué."
    cr.internal_notes = (
        (cr.internal_notes or "") + f"\n\n[IA outbound {call.id}] {summary_text}"
    ).strip()

    if decision.next_action == "lost":
        cr.kanban_column = "lost"
        cr.status = _CRS.LOST.value
        return
    if decision.next_action == "callback":
        cr.kanban_column = "rappel"
        return
    if decision.next_action == "complete_no_action":
        cr.kanban_column = "qualified"
        return

    # RDV — crée un AgendaEvent à l'heure choisie.
    if decision.next_action in ("rdv_demain_am", "rdv_demain_pm", "rdv_apres_demain"):
        from datetime import datetime as _dt, time as _time, timedelta as _td
        from zoneinfo import ZoneInfo
        from app.models.agenda_event import AgendaEvent

        tz = ZoneInfo("America/Montreal")
        today = _dt.now(tz).date()
        if decision.next_action == "rdv_demain_am":
            start_date = today + _td(days=1)
            start_time = _time(10, 0)
        elif decision.next_action == "rdv_demain_pm":
            start_date = today + _td(days=1)
            start_time = _time(14, 0)
        else:
            start_date = today + _td(days=2)
            start_time = _time(10, 0)
        start = _dt.combine(start_date, start_time, tz)
        end = start + _td(hours=1)
        ev = AgendaEvent(
            title=f"RDV qualification : {cr.name}",
            description=(
                f"RDV auto-créé par Léa (IA outbound). Budget : "
                f"{decision.qualified_budget or 'n/c'}. Échéancier : "
                f"{decision.qualified_timeline or 'n/c'}."
            ),
            start_at=start,
            end_at=end,
            scope="construction",
            event_type="rdv",
            contact_request_id=cr.id,
        )
        db.add(ev)
        cr.kanban_column = "rdv_pris"
        if cr.status in (_CRS.NEW.value, _CRS.CONTACTED.value):
            cr.status = _CRS.RDV_PREVU.value
        await db.flush()
        log.info(
            "RDV auto-créé : contact=%d agenda=%d at %s",
            cr.id, ev.id, start.isoformat(),
        )


@router.post(
    "/calls/{contact_request_id}/qualify",
    summary="Lance manuellement la qualification IA outbound d'un lead (admin)",
)
async def trigger_lead_qualification(
    contact_request_id: int, _: CurrentAdmin, db: DBSession
) -> dict:
    """Permet de relancer l'appel IA depuis le CRM (utile si auto a échoué
    ou si on a édité le numéro du lead après coup)."""
    from app.integrations.voice.lead_outbound import start_lead_qualification_call

    # Fire-and-forget, sans délai cette fois (manuel).
    # force=True : le déclencheur manuel admin outrepasse le toggle
    # `lead_auto_callback_enabled` puisque l'admin agit explicitement.
    asyncio.create_task(
        start_lead_qualification_call(
            contact_request_id=contact_request_id, delay_sec=0, force=True,
        )
    )
    return {"queued": True, "contact_request_id": contact_request_id}


@router.post(
    "/twilio/outbound-bridge",
    summary="Webhook Twilio : TwiML du bridge pour un appel sortant",
    response_class=Response,
)
async def twilio_outbound_bridge(request: Request, db: DBSession) -> Response:
    try:
        return await _twilio_outbound_bridge_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_outbound_bridge failed")
        return _safe_error_twiml()


async def _twilio_outbound_bridge_impl(request: Request, db: DBSession) -> Response:
    """TwiML servi quand l'utilisateur interne décroche : <Dial> vers
    la cible CRM. Le query-string contient `call_id` pour nous permettre
    de log la cible exacte (Twilio ne renvoie pas le `To` original).
    """
    params = await _validate_twilio_signature(request)
    provider = _twilio_provider()

    call_id_raw = request.query_params.get("call_id", "")
    target = ""
    if call_id_raw and call_id_raw.isdigit():
        call = (
            await db.execute(
                select(Call).where(Call.id == int(call_id_raw))
            )
        ).scalar_one_or_none()
        if call is not None:
            target = call.to_e164
            # Met à jour le provider_sid avec le CallSid réel si on l'a
            # raté à l'init (latence d'API).
            sid = params.get("CallSid", "")
            if sid and not call.provider_sid.startswith("CA"):
                call.provider_sid = sid
                await db.flush()

    if not target:
        twiml = provider.build_say_and_hangup(
            say="Désolée, cible introuvable. Au revoir.", lang="fr-CA"
        )
        return Response(content=twiml, media_type="application/xml")

    twiml = provider.build_forward_response(forward_to_e164=target)
    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/calls/{call_id}/suggest-followup",
    summary="Génère une suggestion de suivi via Claude (admin)",
)
async def suggest_followup(
    call_id: int, _: CurrentAdmin, db: DBSession
) -> dict:
    """Demande à Claude une suggestion d'action de suivi post-appel.

    Lit le contexte disponible (intent, transcription voicemail, tours
    secrétaire) et propose 1 action concrète (créer follow-up, planifier
    RDV, envoyer soumission, etc.). Persiste dans Call.followup_suggestion
    pour pouvoir le ré-afficher sans refacturer l'IA.
    """
    call = (
        await db.execute(select(Call).where(Call.id == call_id))
    ).scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=404, detail="call_not_found")

    # Construit un contexte compact.
    parts: list[str] = [
        f"Direction : {call.direction}",
        f"De : {call.from_e164} → vers : {call.to_e164}",
    ]
    if call.intent:
        parts.append(f"Intent détecté : {call.intent}")
    if call.duration_sec:
        parts.append(f"Durée : {call.duration_sec}s")
    if call.lead_name:
        parts.append(f"Nom appelant : {call.lead_name}")
    if call.lead_reason:
        parts.append(f"Raison : {call.lead_reason}")
    if call.voicemail_transcription:
        parts.append(f"Voicemail : {call.voicemail_transcription}")
    if call.voicemail_summary:
        parts.append(f"Résumé voicemail : {call.voicemail_summary}")

    # Tours secrétaire (si y en a).
    turns = (
        await db.execute(
            select(CallTurn)
            .where(CallTurn.call_id == call.id)
            .order_by(CallTurn.turn_index)
        )
    ).scalars().all()
    if turns:
        parts.append("Échange secrétaire IA :")
        for t in turns:
            tag = "Secrétaire" if t.role == "assistant" else "Appelant"
            parts.append(f"- {tag} : {t.text}")

    context = "\n".join(parts) or "Aucune information disponible."

    try:
        from app.integrations.ai import chat, Message

        res = await chat(
            messages=[
                Message(
                    role="user",
                    content=(
                        "Contexte d'un appel téléphonique chez Horizon "
                        "Services Immobiliers :\n\n"
                        f"{context}\n\n"
                        "Propose UNE action de suivi concrète (max 2 "
                        "phrases) : rappel, envoi de soumission, "
                        "planification de RDV, ajout au CRM, etc. "
                        "Si aucun suivi n'est nécessaire (spam, "
                        "démarchage…), dis-le simplement."
                    ),
                )
            ],
            system=(
                "Tu aides un entrepreneur québécois à décider quoi faire "
                "après un appel. Réponds en français, 2 phrases max, pas "
                "de markdown. Sois actionnable et direct."
            ),
            max_tokens=200,
            temperature=0.4,
        )
        suggestion = (res.text or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("Suggest followup IA failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"ai_error: {exc}")

    call.followup_suggestion = suggestion
    await db.flush()
    return {"call_id": call.id, "suggestion": suggestion}


# ---------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------


class PhoneNumberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    e164: str
    provider: str
    label: Optional[str]
    forward_to_e164: Optional[str]
    urgency_forward_e164: Optional[str] = None
    closer_forward_e164: Optional[str] = None
    followup_forward_e164: Optional[str] = None
    secretary_mode_active: bool
    lead_auto_callback_enabled: bool = False
    owner_user_id: Optional[int]
    active: bool


class PhoneNumberPatch(BaseModel):
    label: Optional[str] = Field(default=None, max_length=128)
    forward_to_e164: Optional[str] = Field(default=None, max_length=20)
    urgency_forward_e164: Optional[str] = Field(default=None, max_length=20)
    closer_forward_e164: Optional[str] = Field(default=None, max_length=20)
    followup_forward_e164: Optional[str] = Field(default=None, max_length=20)
    secretary_mode_active: Optional[bool] = None
    lead_auto_callback_enabled: Optional[bool] = None
    active: Optional[bool] = None


class CallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone_number_id: int
    direction: str
    status: str
    from_e164: str
    to_e164: str
    forwarded_to_e164: Optional[str]
    started_at: datetime
    answered_at: Optional[datetime]
    ended_at: Optional[datetime]
    duration_sec: Optional[int]
    lang: str
    intent: Optional[str]
    lead_name: Optional[str]
    lead_callback_phone: Optional[str]
    lead_reason: Optional[str]
    contact_request_id: Optional[int]
    was_blocked: bool = False
    was_vip: bool = False
    was_voicemail: bool = False
    voicemail_transcription: Optional[str] = None
    voicemail_summary: Optional[str] = None
    recording_url: Optional[str] = None
    verbatim_transcript: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    followup_suggestion: Optional[str] = None
    caller_kind: Optional[str] = None
    # Numéro du correspondant EXTERNE (l'autre partie) : pour un appel
    # sortant c'est le destinataire (to_e164, ex. le client appelé), pour
    # un entrant c'est l'appelant (from_e164). Évite d'afficher notre
    # propre numéro Horizon dans le journal pour les appels sortants.
    peer_e164: Optional[str] = None
    # Nom du contact identifié (client / locataire / lead / prospect).
    contact_name: Optional[str] = None


class CallTurnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    turn_index: int
    role: str
    text: str
    confidence: Optional[int]
    created_at: datetime


@router.get(
    "/phone-numbers",
    response_model=List[PhoneNumberRead],
    summary="Liste des numéros possédés (admin)",
)
async def list_phone_numbers(_: CurrentAdmin, db: DBSession) -> List[PhoneNumberRead]:
    rows = (
        await db.execute(select(PhoneNumber).order_by(PhoneNumber.id))
    ).scalars().all()
    return [PhoneNumberRead.model_validate(r) for r in rows]


@router.patch(
    "/phone-numbers/{number_id}",
    response_model=PhoneNumberRead,
    summary="Modifie un numéro (toggle secretary_mode, forward_to, label, active)",
)
async def patch_phone_number(
    number_id: int,
    payload: PhoneNumberPatch,
    _: CurrentAdmin,
    db: DBSession,
) -> PhoneNumberRead:
    pn = (
        await db.execute(select(PhoneNumber).where(PhoneNumber.id == number_id))
    ).scalar_one_or_none()
    if pn is None:
        raise HTTPException(status_code=404, detail="phone_number_not_found")
    if payload.label is not None:
        pn.label = payload.label or None
    if payload.forward_to_e164 is not None:
        pn.forward_to_e164 = payload.forward_to_e164.strip() or None
    if payload.urgency_forward_e164 is not None:
        pn.urgency_forward_e164 = (
            payload.urgency_forward_e164.strip() or None
        )
    if payload.closer_forward_e164 is not None:
        pn.closer_forward_e164 = (
            payload.closer_forward_e164.strip() or None
        )
    if payload.followup_forward_e164 is not None:
        pn.followup_forward_e164 = (
            payload.followup_forward_e164.strip() or None
        )
    if payload.secretary_mode_active is not None:
        pn.secretary_mode_active = payload.secretary_mode_active
    if payload.lead_auto_callback_enabled is not None:
        pn.lead_auto_callback_enabled = payload.lead_auto_callback_enabled
    if payload.active is not None:
        pn.active = payload.active
    await db.flush()
    return PhoneNumberRead.model_validate(pn)


class _CallDetail(BaseModel):
    """Détail d'un appel pour le modal côté UI."""

    call: CallRead
    turns: List["CallTurnRead"]


@router.get(
    "/calls/{call_id}/detail",
    response_model=_CallDetail,
    summary=(
        "Détail complet d'un appel (call + tours IA) — "
        "accessible à tout utilisateur authentifié"
    ),
)
async def get_call_detail(
    call_id: int, _: CurrentUser, db: DBSession
) -> _CallDetail:
    """Renvoie la Call + ses tours IA, pour l'affichage dans le
    modal de détail ouvert depuis CallHistoryDropdown."""
    call = (
        await db.execute(select(Call).where(Call.id == call_id))
    ).scalar_one_or_none()
    if call is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Call not found"
        )
    turns = (
        await db.execute(
            select(CallTurn)
            .where(CallTurn.call_id == call_id)
            .order_by(CallTurn.turn_index)
        )
    ).scalars().all()
    return _CallDetail(
        call=CallRead.model_validate(call),
        turns=[CallTurnRead.model_validate(t) for t in turns],
    )


@router.get(
    "/calls/search",
    response_model=List[CallRead],
    summary=(
        "Recherche d'appels par numéro ou nom de lead — "
        "accessible à tout utilisateur authentifié"
    ),
)
async def search_calls(
    _: CurrentUser,
    db: DBSession,
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=30, ge=1, le=100),
) -> List[CallRead]:
    """Recherche libre d'appels — match sur le numéro (partial,
    digits-only — donc « 514-555 » trouve « +15145551234 ») ou le nom
    du lead capturé sur l'appel. Trié du plus récent au plus ancien.
    Visible par tout utilisateur authentifié — sert au composant
    Historique d'appels affiché dans les volets construction,
    prospection et téléphonie."""
    q = (q or "").strip()
    stmt = select(Call)
    if q:
        digits = "".join(c for c in q if c.isdigit())
        clauses = []
        if digits:
            like = f"%{digits}%"
            clauses.append(Call.from_e164.ilike(like))
            clauses.append(Call.to_e164.ilike(like))
            clauses.append(Call.forwarded_to_e164.ilike(like))
        # Match texte sur :
        #  - lead_name : nom capturé pendant l'appel,
        #  - lead_reason : raison brève captée par Léa,
        #  - verbatim_transcript : ce qu'on a dit côté navigateur,
        #  - voicemail_transcription : transcription auto Twilio.
        # Permet une recherche du genre « est-ce qu'on a parlé de
        # cuisine avec Steven ? » via le champ unique du dropdown.
        text_like = f"%{q}%"
        clauses.append(Call.lead_name.ilike(text_like))
        clauses.append(Call.lead_reason.ilike(text_like))
        clauses.append(Call.verbatim_transcript.ilike(text_like))
        clauses.append(Call.voicemail_transcription.ilike(text_like))
        # OR sur tous les critères — au moins un match suffit.
        cond = clauses[0]
        for extra in clauses[1:]:
            cond = cond | extra
        stmt = stmt.where(cond)
    stmt = stmt.order_by(Call.started_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [CallRead.model_validate(r) for r in rows]


@router.get(
    "/calls",
    response_model=List[CallRead],
    summary="Journal d'appels récent (admin) — optionnel : filtre par entité",
)
async def list_calls(
    _: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
    entity_type: Optional[str] = Query(default=None),
    entity_id: Optional[int] = Query(default=None),
) -> List[CallRead]:
    stmt = select(Call)
    if entity_type:
        stmt = stmt.where(Call.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(Call.entity_id == entity_id)
    stmt = stmt.order_by(Call.started_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    # Numéro pair (correspondant externe) + nom du contact identifié.
    # Pour un sortant, le correspondant est `to_e164` (le client appelé) ;
    # pour un entrant, c'est `from_e164`. On résout le nom via le CRM,
    # avec un cache par numéro pour limiter les requêtes.
    out: List[CallRead] = []
    ident_cache: dict = {}
    for r in rows:
        cr = CallRead.model_validate(r)
        peer = (
            r.to_e164
            if r.direction == CallDirection.OUTBOUND.value
            else r.from_e164
        ) or ""
        cr.peer_e164 = peer or None
        if peer:
            if peer not in ident_cache:
                try:
                    ident_cache[peer] = await identify_caller(db, peer)
                except Exception:  # noqa: BLE001
                    ident_cache[peer] = None
            ident = ident_cache[peer]
            if ident is not None:
                cr.contact_name = ident.name
                if ident.kind != CallerKind.UNKNOWN:
                    cr.caller_kind = ident.kind.value
        out.append(cr)
    return out


@router.get(
    "/calls/{call_id}/turns",
    response_model=List[CallTurnRead],
    summary="Transcription tour-par-tour d'un appel (admin)",
)
async def get_call_turns(
    call_id: int, _: CurrentAdmin, db: DBSession
) -> List[CallTurnRead]:
    rows = (
        await db.execute(
            select(CallTurn)
            .where(CallTurn.call_id == call_id)
            .order_by(CallTurn.turn_index)
        )
    ).scalars().all()
    return [CallTurnRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------
# SMS (Phase 6) — bidirectionnel via le même numéro 438
# ---------------------------------------------------------------------


@router.post(
    "/twilio/sms",
    summary="Webhook Twilio : SMS entrant",
    response_class=Response,
)
async def twilio_incoming_sms(request: Request, db: DBSession) -> Response:
    """Twilio POST ici à chaque SMS entrant. On stocke + on identifie
    l'expéditeur via le CRM. Notif cloche aux owners.

    Réponse : `<Response/>` vide (pas de réponse SMS auto pour l'instant —
    un futur SMS bot IA pourrait répondre ici).
    """
    try:
        return await _twilio_incoming_sms_impl(request, db)
    except HTTPException as _http_exc:
        # On préfère un TwiML poli en français à la lecture du message
        # d'erreur anglais par défaut de Twilio. Les 401 signature
        # mismatch + 503 provider not configured sont loggés mais
        # l'appelant entend « Désolée, souci technique ».
        log.warning(
            "twilio webhook rejected: %d %s",
            _http_exc.status_code, _http_exc.detail,
        )
        return _safe_error_twiml()
    except Exception:
        log.exception("twilio_incoming_sms failed")
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
            media_type="application/xml",
        )


async def _twilio_incoming_sms_impl(request: Request, db: DBSession) -> Response:
    params = await _validate_twilio_signature(request)

    message_sid = params.get("MessageSid", "")
    from_e164 = params.get("From", "")
    to_e164 = params.get("To", "")
    body = params.get("Body", "")
    num_media = int(params.get("NumMedia", "0") or 0)

    if not (message_sid and from_e164 and to_e164):
        raise HTTPException(status_code=400, detail="Missing MessageSid / From / To")

    pn = (
        await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.e164 == to_e164, PhoneNumber.active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if pn is None:
        log.warning("Inbound SMS to unknown number %s", to_e164)
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
            media_type="application/xml",
        )

    # Idempotent : Twilio peut rejouer.
    existing = (
        await db.execute(
            select(VoiceSms).where(VoiceSms.provider_sid == message_sid)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
            media_type="application/xml",
        )

    # Récupère les media URLs si MMS.
    import json as _json

    media_urls: list[str] = []
    for i in range(num_media):
        url = params.get(f"MediaUrl{i}")
        if url:
            media_urls.append(url)

    # Identification CRM (même logique que les appels).
    identified = await identify_caller(db, from_e164)
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    if identified.kind != CallerKind.UNKNOWN and identified.entity_id:
        from app.integrations.voice.caller_identity import CallerKind as _CK

        kind_to_entity = {
            _CK.CLIENT: "client",
            _CK.LOCATAIRE: "locataire",
            _CK.LEAD_PROSPECTION: "prospection_lead",
            _CK.LEAD_WEB: "contact_request",
        }
        entity_type = kind_to_entity.get(identified.kind)
        entity_id = identified.entity_id

    sms = VoiceSms(
        phone_number_id=pn.id,
        provider_sid=message_sid,
        direction="inbound",
        status="received",
        from_e164=from_e164,
        to_e164=to_e164,
        body=body or None,
        media_urls=_json.dumps(media_urls) if media_urls else None,
        num_media=num_media,
        caller_kind=identified.kind.value,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(sms)
    await db.flush()

    # Notif cloche aux owners (ou à l'owner du numéro si défini).
    try:
        from app.models.notification import Notification
        from app.models.user import User

        if pn.owner_user_id:
            user_ids = [pn.owner_user_id]
        else:
            user_ids = list(
                (
                    await db.execute(
                        select(User.id).where(User.role == "owner")
                    )
                ).scalars().all()
            )
        preview = (body or "")[:140]
        for uid in user_ids:
            db.add(
                Notification(
                    user_id=uid,
                    kind="sms_received",
                    title=f"SMS de {identified.name or from_e164}",
                    body=preview or "(MMS sans texte)",
                    href=f"/telephonie?sms={sms.id}",
                )
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("SMS notification failed: %s", exc)

    await db.flush()
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
        media_type="application/xml",
    )


# ---------- SMS admin (envoi + liste threadée) ----------


class SmsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone_number_id: int
    provider_sid: str
    direction: str
    status: str
    from_e164: str
    to_e164: str
    body: Optional[str]
    media_urls: Optional[str]
    num_media: int
    received_at: datetime
    sent_at: Optional[datetime]
    caller_kind: Optional[str]
    entity_type: Optional[str]
    entity_id: Optional[int]
    sent_by_user_id: Optional[int]
    read_at: Optional[datetime]


class SmsSend(BaseModel):
    to_e164: str = Field(min_length=4, max_length=20)
    body: str = Field(min_length=1, max_length=1600)
    from_phone_number_id: Optional[int] = None


@router.get(
    "/sms",
    response_model=List[SmsRead],
    summary="Liste les SMS (admin, optionnel filtre par contact)",
)
async def list_sms(
    _: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=100, ge=1, le=500),
    peer_e164: Optional[str] = Query(default=None, description="Filtre par numéro pair (entrant ou sortant)"),
    entity_type: Optional[str] = Query(default=None),
    entity_id: Optional[int] = Query(default=None),
) -> List[SmsRead]:
    from sqlalchemy import or_

    stmt = select(VoiceSms)
    if peer_e164:
        stmt = stmt.where(
            or_(VoiceSms.from_e164 == peer_e164, VoiceSms.to_e164 == peer_e164)
        )
    if entity_type:
        stmt = stmt.where(VoiceSms.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(VoiceSms.entity_id == entity_id)
    stmt = stmt.order_by(VoiceSms.received_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [SmsRead.model_validate(r) for r in rows]


# -- Communications timeline (vue 360 pour les fiches CRM) --------
# Endpoint dédié, accessible à tout utilisateur authentifié (pas
# admin) : retourne la chronologie fusionnée appels + SMS pour une
# entité CRM précise (lead, client, locataire, contact_request).
# Read-only. Sert l'onglet « Communications » dans /prospection,
# /app/crm, /app/clients. On scope strictement par (entity_type,
# entity_id) — pas de listing global.
class CommunicationEvent(BaseModel):
    kind: str  # "call" | "sms" | "email"
    id: int
    at: datetime
    direction: str  # inbound | outbound
    status: str
    from_e164: str = ""
    to_e164: str = ""
    # Champs propres aux appels
    duration_sec: Optional[int] = None
    intent: Optional[str] = None
    was_voicemail: bool = False
    voicemail_summary: Optional[str] = None
    followup_suggestion: Optional[str] = None
    # Champs propres aux SMS
    body: Optional[str] = None
    num_media: int = 0
    # Champs propres aux courriels
    subject: Optional[str] = None
    email_from: Optional[str] = None
    email_to: Optional[str] = None
    # Résumé IA de l'enregistrement (appels)
    call_summary: Optional[str] = None
    has_recording: bool = False


_VALID_ENTITY_TYPES = {"client", "locataire", "prospection_lead", "contact_request"}


@router.get(
    "/communications/{entity_type}/{entity_id}",
    response_model=List[CommunicationEvent],
    summary="Chronologie unifiée appels + SMS pour une entité CRM",
)
async def list_communications_for_entity(
    entity_type: str,
    entity_id: int,
    _: CurrentUser,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> List[CommunicationEvent]:
    if entity_type not in _VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "entity_type doit être l'un de : "
                + ", ".join(sorted(_VALID_ENTITY_TYPES))
            ),
        )

    calls = (
        await db.execute(
            select(Call)
            .where(Call.entity_type == entity_type, Call.entity_id == entity_id)
            .order_by(Call.started_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    sms_rows = (
        await db.execute(
            select(VoiceSms)
            .where(
                VoiceSms.entity_type == entity_type,
                VoiceSms.entity_id == entity_id,
            )
            .order_by(VoiceSms.received_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    events: List[CommunicationEvent] = []
    for c in calls:
        events.append(
            CommunicationEvent(
                kind="call",
                id=c.id,
                at=c.started_at,
                direction=c.direction,
                status=c.status,
                from_e164=c.from_e164,
                to_e164=c.to_e164,
                duration_sec=c.duration_sec,
                intent=c.intent,
                was_voicemail=bool(c.was_voicemail),
                voicemail_summary=c.voicemail_summary,
                followup_suggestion=c.followup_suggestion,
                call_summary=c.recording_summary,
                has_recording=bool(c.recording_url),
            )
        )
    for s in sms_rows:
        events.append(
            CommunicationEvent(
                kind="sms",
                id=s.id,
                at=s.received_at,
                direction=s.direction,
                status=s.status,
                from_e164=s.from_e164,
                to_e164=s.to_e164,
                body=s.body,
                num_media=s.num_media or 0,
            )
        )

    email_rows = (
        await db.execute(
            select(EmailLog)
            .where(
                EmailLog.entity_type == entity_type,
                EmailLog.entity_id == entity_id,
            )
            .order_by(EmailLog.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    for em in email_rows:
        events.append(
            CommunicationEvent(
                kind="email",
                id=em.id,
                at=em.sent_at or em.received_at or em.created_at,
                direction=em.direction,
                status=em.status,
                subject=em.subject,
                email_from=em.from_email,
                email_to=em.to_email,
                body=em.body_preview or em.body_html,
            )
        )

    events.sort(key=lambda e: e.at, reverse=True)
    return events[:limit]


class EmailComposeRequest(BaseModel):
    to: str = Field(..., min_length=3, max_length=320)
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1)
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None


@router.post(
    "/email",
    response_model=CommunicationEvent,
    status_code=status.HTTP_201_CREATED,
    summary="Envoie un courriel à une entité CRM et le logge dans le fil",
)
async def send_email_comms(
    payload: EmailComposeRequest, user: CurrentUser, db: DBSession
) -> CommunicationEvent:
    from app.integrations.email_graph import get_mailer

    mailer = get_mailer()
    if not mailer.ready:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Courriel non configuré (AZURE_* / MAIL_FROM_EMAIL).",
        )
    body_html = (
        '<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;'
        'color:#0f172a;line-height:1.5">'
        + payload.body.strip().replace("\n", "<br>")
        + "</div>"
    )
    try:
        await mailer.send(
            to=[payload.to.strip()],
            subject=payload.subject.strip(),
            html_body=body_html,
            reply_to=mailer.sender,
        )
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"Envoi échoué : {exc}"
        )
    now = datetime.now(timezone.utc)
    row = EmailLog(
        direction="outbound",
        status="sent",
        from_email=mailer.sender,
        to_email=payload.to.strip(),
        subject=payload.subject.strip(),
        body_html=body_html,
        body_preview=payload.body.strip()[:2000],
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        sent_by_user_id=user.id,
        sent_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return CommunicationEvent(
        kind="email",
        id=row.id,
        at=now,
        direction="outbound",
        status="sent",
        subject=row.subject,
        email_from=row.from_email,
        email_to=row.to_email,
        body=row.body_preview,
    )


class CallSummaryResult(BaseModel):
    call_id: int
    summary: Optional[str] = None
    transcription: Optional[str] = None


@router.post(
    "/calls/{call_id}/summarize",
    response_model=CallSummaryResult,
    summary="Transcrit + résume l'enregistrement d'un appel (Groq + IA)",
)
async def summarize_call(
    call_id: int, user: CurrentUser, db: DBSession
) -> CallSummaryResult:
    from app.services.call_recording_summary import (
        CallSummaryError,
        summarize_call_recording,
    )

    call = (
        await db.execute(select(Call).where(Call.id == call_id))
    ).scalar_one_or_none()
    if call is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appel introuvable.")
    try:
        await summarize_call_recording(db, call, force=True)
    except CallSummaryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    await db.commit()
    return CallSummaryResult(
        call_id=call.id,
        summary=call.recording_summary,
        transcription=call.recording_transcription,
    )


@router.get(
    "/sms/threads",
    summary="Threads SMS : groupe par numéro pair avec last message + unread count",
)
async def list_sms_threads(
    _: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> List[dict]:
    """Pour la vue Messages (inbox). Renvoie une ligne par contact
    pair (numéro extérieur à Horizon), avec son dernier SMS, le nombre
    de non-lus et l'identification CRM si reconnue.
    """
    rows = (
        await db.execute(
            select(VoiceSms).order_by(VoiceSms.received_at.desc()).limit(limit * 4)
        )
    ).scalars().all()
    # Group by peer (extérieur).
    threads: dict[str, dict] = {}
    for r in rows:
        peer = r.from_e164 if r.direction == "inbound" else r.to_e164
        if peer in threads:
            t = threads[peer]
            if r.direction == "inbound" and r.read_at is None:
                t["unread"] += 1
            continue
        threads[peer] = {
            "peer_e164": peer,
            "name": None,
            "last_message": {
                "id": r.id,
                "direction": r.direction,
                "body": r.body,
                "received_at": r.received_at.isoformat(),
                "num_media": r.num_media,
            },
            "caller_kind": r.caller_kind,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "unread": (1 if (r.direction == "inbound" and r.read_at is None) else 0),
        }
        if len(threads) >= limit:
            break

    # Identification CRM live : on retrouve le NOM du contact (et on
    # rafraîchit le badge) pour chaque numéro pair connu, afin d'afficher
    # « Bob Tremblay » plutôt qu'un numéro nu dans l'inbox.
    _KIND_TO_ENTITY = {
        CallerKind.CLIENT: "client",
        CallerKind.LOCATAIRE: "locataire",
        CallerKind.LEAD_PROSPECTION: "prospection_lead",
        CallerKind.LEAD_WEB: "contact_request",
    }
    for peer, t in threads.items():
        try:
            ident = await identify_caller(db, peer)
        except Exception:  # noqa: BLE001
            continue
        t["name"] = ident.name
        if ident.kind != CallerKind.UNKNOWN:
            t["caller_kind"] = ident.kind.value
            t["entity_type"] = _KIND_TO_ENTITY.get(
                ident.kind, t.get("entity_type")
            )
            t["entity_id"] = ident.entity_id

    return list(threads.values())


@router.post(
    "/sms",
    response_model=SmsRead,
    status_code=status.HTTP_201_CREATED,
    summary="Envoie un SMS via notre numéro (admin)",
)
async def send_sms(
    payload: SmsSend, user: CurrentUser, db: DBSession
) -> SmsRead:
    target = _normalize_e164(payload.to_e164)
    if not target.startswith("+"):
        raise HTTPException(status_code=400, detail="to_e164 must be E.164 (+...)")

    if payload.from_phone_number_id:
        pn = (
            await db.execute(
                select(PhoneNumber).where(
                    PhoneNumber.id == payload.from_phone_number_id,
                    PhoneNumber.active.is_(True),
                )
            )
        ).scalar_one_or_none()
    else:
        pn = (
            await db.execute(
                select(PhoneNumber)
                .where(PhoneNumber.active.is_(True))
                .order_by(PhoneNumber.id)
                .limit(1)
            )
        ).scalar_one_or_none()
    if pn is None:
        raise HTTPException(status_code=400, detail="no_active_phone_number")

    provider = _twilio_provider()
    try:
        data = await provider.send_sms(
            from_e164=pn.e164, to_e164=target, body=payload.body
        )
    except Exception as exc:
        log.exception("Twilio SMS send failed")
        raise HTTPException(status_code=502, detail=f"twilio_error: {exc}")

    msg_sid = str(data.get("sid") or "")
    if not msg_sid:
        raise HTTPException(status_code=502, detail="twilio_no_sid")

    # Identification CRM (au cas où le destinataire est connu).
    identified = await identify_caller(db, target)
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    if identified.kind != CallerKind.UNKNOWN and identified.entity_id:
        from app.integrations.voice.caller_identity import CallerKind as _CK

        kind_to_entity = {
            _CK.CLIENT: "client",
            _CK.LOCATAIRE: "locataire",
            _CK.LEAD_PROSPECTION: "prospection_lead",
            _CK.LEAD_WEB: "contact_request",
        }
        entity_type = kind_to_entity.get(identified.kind)
        entity_id = identified.entity_id

    sms = VoiceSms(
        phone_number_id=pn.id,
        provider_sid=msg_sid,
        direction="outbound",
        status=str(data.get("status") or "queued"),
        from_e164=pn.e164,
        to_e164=target,
        body=payload.body,
        sent_at=datetime.now(timezone.utc),
        caller_kind=identified.kind.value,
        entity_type=entity_type,
        entity_id=entity_id,
        sent_by_user_id=user.id,
    )
    db.add(sms)
    await db.flush()
    return SmsRead.model_validate(sms)


@router.post(
    "/sms/{sms_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Marque un SMS entrant comme lu",
)
async def mark_sms_read(
    sms_id: int, _: CurrentUser, db: DBSession
) -> Response:
    sms = (
        await db.execute(select(VoiceSms).where(VoiceSms.id == sms_id))
    ).scalar_one_or_none()
    if sms is None:
        raise HTTPException(status_code=404, detail="sms_not_found")
    if sms.read_at is None:
        sms.read_at = datetime.now(timezone.utc)
        await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Diagnostic infra téléphonie (admin) ------------


@router.post(
    "/diag/bootstrap",
    summary="Relance manuellement le bootstrap Twilio (admin)",
)
async def trigger_bootstrap(_: CurrentAdmin) -> dict:
    """Relance bootstrap_twilio() avec force=True pour reconfigurer
    le webhook URL chez Twilio + créer/refresh la ligne PhoneNumber
    en DB. Utile quand le bootstrap auto a échoué au démarrage."""
    from app.scripts.twilio_bootstrap import bootstrap_twilio

    try:
        rc = await bootstrap_twilio(force=True)
        return {"ok": rc == 0, "return_code": rc}
    except Exception as exc:  # noqa: BLE001
        log.exception("Manual bootstrap failed")
        return {"ok": False, "error": str(exc)}


@router.post(
    "/diag/dedupe",
    summary="Fusionne les PhoneNumber doublons (admin)",
)
async def trigger_dedupe(_: CurrentAdmin, db: DBSession) -> dict:
    """Cherche les lignes PhoneNumber qui ont les mêmes 10 derniers
    chiffres mais des e164 différents (ex. « 14388002979 » vs
    « +14388002979 ») et les fusionne. Retourne un rapport détaillé."""
    from sqlalchemy import func, update

    from app.models.voice import VoiceBusinessHours, VoiceFilter, VoiceSms

    try:
        env_raw = (os.getenv("TWILIO_PHONE_NUMBER") or "").strip()
        canonical_e164 = _normalize_e164(env_raw) if env_raw else ""
        if not canonical_e164:
            return {"ok": False, "error": "TWILIO_PHONE_NUMBER env vide"}

        digits_canonical = "".join(c for c in canonical_e164 if c.isdigit())[-10:]

        rows = (
            await db.execute(
                select(PhoneNumber).where(
                    func.right(
                        func.regexp_replace(
                            PhoneNumber.e164, r"[^0-9]", "", "g"
                        ),
                        10,
                    )
                    == digits_canonical
                )
            )
        ).scalars().all()

        report: dict = {
            "ok": True,
            "canonical_e164": canonical_e164,
            "matched_rows": [
                {
                    "id": r.id,
                    "e164": r.e164,
                    "secretary_mode_active": r.secretary_mode_active,
                    "lead_auto_callback_enabled": r.lead_auto_callback_enabled,
                    "forward_to_e164": r.forward_to_e164,
                    "provider_sid": r.provider_sid,
                }
                for r in rows
            ],
            "deleted_count": 0,
        }

        if len(rows) <= 1:
            report["message"] = "Aucun doublon trouvé"
            return report

        # Élit la canonique : celle dont e164 == canonical_e164, sinon
        # la 1re créée.
        keep = next((r for r in rows if r.e164 == canonical_e164), None)
        if keep is None:
            keep = min(rows, key=lambda r: r.id)
            keep.e164 = canonical_e164
        dups = [r for r in rows if r.id != keep.id]

        for dup in dups:
            # Snapshot des champs AVANT delete pour pouvoir les copier
            # sur keep ensuite.
            snap = {
                "secretary_mode_active": dup.secretary_mode_active,
                "lead_auto_callback_enabled": dup.lead_auto_callback_enabled,
                "active": dup.active,
                "forward_to_e164": dup.forward_to_e164,
                "provider_sid": dup.provider_sid,
                "label": dup.label,
            }

            # 1) Réassigne les FK enfants vers keep.id (UPDATE).
            for cls in (Call, VoiceSms, VoiceFilter, VoiceBusinessHours):
                await db.execute(
                    update(cls)
                    .where(cls.phone_number_id == dup.id)
                    .values(phone_number_id=keep.id)
                )

            # 2) Delete dup AVANT de copier provider_sid sur keep —
            # sinon UNIQUE constraint sur provider_sid se déclenche
            # (les deux lignes ont brièvement le même SID en mémoire).
            await db.delete(dup)
            await db.flush()

            # 3) Maintenant safe : merge les champs sur keep.
            keep.secretary_mode_active = (
                keep.secretary_mode_active or snap["secretary_mode_active"]
            )
            keep.lead_auto_callback_enabled = (
                keep.lead_auto_callback_enabled or snap["lead_auto_callback_enabled"]
            )
            keep.active = keep.active or snap["active"]
            if not keep.forward_to_e164 and snap["forward_to_e164"]:
                keep.forward_to_e164 = snap["forward_to_e164"]
            if not keep.provider_sid and snap["provider_sid"]:
                keep.provider_sid = snap["provider_sid"]
            if not keep.label and snap["label"]:
                keep.label = snap["label"]
            await db.flush()
        report["deleted_count"] = len(dups)
        report["kept_id"] = keep.id
        report["kept_state"] = {
            "secretary_mode_active": keep.secretary_mode_active,
            "lead_auto_callback_enabled": keep.lead_auto_callback_enabled,
            "active": keep.active,
        }
        report["message"] = (
            f"{len(dups)} doublon(s) fusionné(s) vers id={keep.id} "
            f"(e164={keep.e164})"
        )
        return report
    except Exception as exc:  # noqa: BLE001
        log.exception("Dedupe failed")
        return {"ok": False, "error": str(exc)}


@router.get(
    "/diag",
    summary="État du système téléphonie pour troubleshooting (admin)",
)
async def voice_diag(_: CurrentAdmin, db: DBSession) -> dict:
    """Reporte tout ce qui peut faire planter le webhook entrant :
    env vars, tables DB, provider IA, état Twilio. Sert quand l'appelant
    tombe sur le TwiML d'erreur poli (`_safe_error_twiml`).
    """
    from sqlalchemy import text as _text

    out: dict = {}

    # 1) Env vars (présence seulement, pas de valeur pour les secrets)
    out["env"] = {
        "TWILIO_ACCOUNT_SID": bool(os.getenv("TWILIO_ACCOUNT_SID")),
        "TWILIO_AUTH_TOKEN": bool(os.getenv("TWILIO_AUTH_TOKEN")),
        "TWILIO_PHONE_NUMBER": os.getenv("TWILIO_PHONE_NUMBER") or None,
        "TWILIO_FORWARD_TO": os.getenv("TWILIO_FORWARD_TO") or None,
        "VOICE_WEBHOOK_BASE_URL": os.getenv("VOICE_WEBHOOK_BASE_URL")
        or "https://h2-0.onrender.com",
        "TWILIO_TWIML_APP_SID": bool(os.getenv("TWILIO_TWIML_APP_SID")),
        "TWILIO_API_KEY_SID": bool(os.getenv("TWILIO_API_KEY_SID")),
        "TWILIO_API_KEY_SECRET": bool(os.getenv("TWILIO_API_KEY_SECRET")),
        "voice_sdk_configured": voice_sdk_configured(),
        "GEMINI_API_KEY": bool(os.getenv("GEMINI_API_KEY")),
        "ANTHROPIC_API_KEY": bool(os.getenv("ANTHROPIC_API_KEY")),
        "GROQ_API_KEY": bool(os.getenv("GROQ_API_KEY")),
    }

    # 2) Provider IA actif (chat) — on essaie de l'initialiser sans
    #    déclencher d'appel API.
    try:
        from app.integrations.ai import current_provider, is_configured

        out["ai"] = {
            "configured": is_configured(),
            "provider": current_provider(),
        }
    except Exception as exc:  # noqa: BLE001
        out["ai"] = {"error": str(exc)}

    # 3) Tables téléphonie présentes ?
    required_tables = [
        "voice_phone_numbers",
        "voice_calls",
        "voice_call_routes",
        "voice_call_transcripts",
        "voice_call_turns",
        "voice_filters",
        "voice_business_hours",
        "voice_caller_intel",
        "voice_usage_daily",
        "voice_client_presence",
        "voice_sms",
    ]
    tables_status: dict[str, str] = {}
    for tbl in required_tables:
        try:
            res = await db.execute(
                _text(f"SELECT to_regclass('public.{tbl}')")
            )
            present = res.scalar() is not None
            tables_status[tbl] = "ok" if present else "MISSING"
        except Exception as exc:  # noqa: BLE001
            tables_status[tbl] = f"error: {exc}"
    out["tables"] = tables_status

    # 4) Colonnes critiques ajoutées via ALTER (les plus récentes)
    columns_to_check = [
        ("voice_phone_numbers", "secretary_mode_active"),
        ("voice_phone_numbers", "lead_auto_callback_enabled"),
        ("voice_calls", "lang"),
        ("voice_calls", "intent"),
        ("voice_calls", "caller_kind"),
        ("voice_calls", "entity_type"),
        ("voice_calls", "entity_id"),
        ("voice_calls", "was_blocked"),
        ("voice_calls", "was_voicemail"),
        ("voice_calls", "voicemail_transcription"),
        ("voice_calls", "followup_suggestion"),
    ]
    cols_status: dict[str, str] = {}
    for tbl, col in columns_to_check:
        key = f"{tbl}.{col}"
        try:
            res = await db.execute(
                _text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c"
                ),
                {"t": tbl, "c": col},
            )
            cols_status[key] = "ok" if res.scalar() else "MISSING"
        except Exception as exc:  # noqa: BLE001
            cols_status[key] = f"error: {exc}"
    out["columns"] = cols_status

    # 5) PhoneNumber configuré ?
    try:
        rows = (
            await db.execute(select(PhoneNumber).order_by(PhoneNumber.id))
        ).scalars().all()
        out["phone_numbers"] = [
            {
                "id": r.id,
                "e164": r.e164,
                "provider_sid": r.provider_sid,
                "active": r.active,
                "secretary_mode_active": r.secretary_mode_active,
                "lead_auto_callback_enabled": getattr(
                    r, "lead_auto_callback_enabled", None
                ),
                "forward_to_e164": r.forward_to_e164,
            }
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        out["phone_numbers"] = {"error": str(exc)}

    # 6) Compteur usage du jour
    try:
        from datetime import date as _date

        today = _date.today().isoformat()
        usage = (
            await db.execute(
                select(VoiceUsageDaily).where(
                    VoiceUsageDaily.usage_date == today
                )
            )
        ).scalar_one_or_none()
        out["usage_today"] = (
            {
                "cents": usage.cents_spent,
                "calls": usage.calls_count,
                "spam_blocked": usage.spam_blocked,
            }
            if usage
            else {"cents": 0, "calls": 0, "spam_blocked": 0}
        )
    except Exception as exc:  # noqa: BLE001
        out["usage_today"] = {"error": str(exc)}

    return out


# ---------- Anti-spam : stats + intel (admin) ------------


class UsageDayRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    usage_date: str
    cents_spent: int
    calls_count: int
    spam_blocked: int


class CallerIntelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    from_e164: str
    line_type: Optional[str]
    caller_name: Optional[str]
    spam_hangup_count: int
    banned_until: Optional[datetime]
    last_verstat: Optional[str]
    notes: Optional[str]


@router.get(
    "/usage/today",
    response_model=UsageDayRead,
    summary="Usage Twilio du jour (cents dépensés, appels, spam bloqué)",
)
async def get_usage_today(_: CurrentAdmin, db: DBSession) -> UsageDayRead:
    from datetime import date as _date

    today = _date.today().isoformat()
    row = (
        await db.execute(
            select(VoiceUsageDaily).where(VoiceUsageDaily.usage_date == today)
        )
    ).scalar_one_or_none()
    if row is None:
        return UsageDayRead(
            usage_date=today, cents_spent=0, calls_count=0, spam_blocked=0
        )
    return UsageDayRead.model_validate(row)


from app.models.voice import VoiceCallerIntel as _VCI  # for the next endpoint


@router.get(
    "/caller-intel",
    response_model=List[CallerIntelRead],
    summary="Renseignements anti-spam par numéro (admin)",
)
async def list_caller_intel(
    _: CurrentAdmin,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
    banned_only: bool = Query(default=False),
) -> List[CallerIntelRead]:
    stmt = select(_VCI)
    if banned_only:
        from datetime import datetime as _dt, timezone as _tz

        stmt = stmt.where(_VCI.banned_until > _dt.now(_tz.utc))
    stmt = stmt.order_by(_VCI.updated_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [CallerIntelRead.model_validate(r) for r in rows]


# ---------- Filtres (blocklist + whitelist VIP) Phase 3 ------------


class FilterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone_number_id: int
    kind: str
    pattern: Optional[str]
    label: Optional[str]
    active: bool


class FilterCreate(BaseModel):
    phone_number_id: int
    kind: str = Field(pattern="^(block|vip)$")
    pattern: Optional[str] = Field(default=None, max_length=32)
    label: Optional[str] = Field(default=None, max_length=255)


@router.get(
    "/filters",
    response_model=List[FilterRead],
    summary="Liste des filtres blocklist + VIP (admin)",
)
async def list_filters(
    _: CurrentAdmin,
    db: DBSession,
    phone_number_id: Optional[int] = Query(default=None),
) -> List[FilterRead]:
    stmt = select(VoiceFilter)
    if phone_number_id is not None:
        stmt = stmt.where(VoiceFilter.phone_number_id == phone_number_id)
    stmt = stmt.order_by(VoiceFilter.kind, VoiceFilter.id)
    rows = (await db.execute(stmt)).scalars().all()
    return [FilterRead.model_validate(r) for r in rows]


@router.post(
    "/filters",
    response_model=FilterRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crée un filtre (block ou vip)",
)
async def create_filter(
    payload: FilterCreate, _: CurrentAdmin, db: DBSession
) -> FilterRead:
    # Sanity : pn existe
    pn = (
        await db.execute(
            select(PhoneNumber).where(PhoneNumber.id == payload.phone_number_id)
        )
    ).scalar_one_or_none()
    if pn is None:
        raise HTTPException(status_code=404, detail="phone_number_not_found")
    f = VoiceFilter(
        phone_number_id=payload.phone_number_id,
        kind=payload.kind,
        pattern=(payload.pattern or None),
        label=payload.label,
        active=True,
    )
    db.add(f)
    await db.flush()
    return FilterRead.model_validate(f)


@router.delete(
    "/filters/{filter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprime un filtre",
)
async def delete_filter(
    filter_id: int, _: CurrentAdmin, db: DBSession
) -> Response:
    f = (
        await db.execute(select(VoiceFilter).where(VoiceFilter.id == filter_id))
    ).scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="filter_not_found")
    await db.delete(f)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Heures d'ouverture Phase 3 ------------


class BusinessHoursRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone_number_id: int
    day_of_week: int
    open_time: str
    close_time: str
    timezone: str


class BusinessHoursReplace(BaseModel):
    """Remplace TOUTES les plages d'un numéro par celles fournies.

    Pour effacer toutes les règles (= ouvert 24/7), envoyer `hours=[]`.
    """

    phone_number_id: int
    hours: List["BusinessHoursItem"]


class BusinessHoursItem(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    # Format "HH:MM" 24h.
    open_time: str
    close_time: str
    timezone: str = "America/Montreal"


BusinessHoursReplace.model_rebuild()


@router.get(
    "/business-hours",
    response_model=List[BusinessHoursRead],
    summary="Liste des plages horaires (admin, par numéro)",
)
async def list_business_hours(
    _: CurrentAdmin,
    db: DBSession,
    phone_number_id: int = Query(...),
) -> List[BusinessHoursRead]:
    rows = (
        await db.execute(
            select(VoiceBusinessHours)
            .where(VoiceBusinessHours.phone_number_id == phone_number_id)
            .order_by(VoiceBusinessHours.day_of_week, VoiceBusinessHours.open_time)
        )
    ).scalars().all()
    return [
        BusinessHoursRead(
            id=r.id,
            phone_number_id=r.phone_number_id,
            day_of_week=r.day_of_week,
            open_time=r.open_time.strftime("%H:%M"),
            close_time=r.close_time.strftime("%H:%M"),
            timezone=r.timezone,
        )
        for r in rows
    ]


@router.put(
    "/business-hours",
    response_model=List[BusinessHoursRead],
    summary="Remplace toutes les plages horaires du numéro (atomique)",
)
async def replace_business_hours(
    payload: BusinessHoursReplace, _: CurrentAdmin, db: DBSession
) -> List[BusinessHoursRead]:
    pn = (
        await db.execute(
            select(PhoneNumber).where(PhoneNumber.id == payload.phone_number_id)
        )
    ).scalar_one_or_none()
    if pn is None:
        raise HTTPException(status_code=404, detail="phone_number_not_found")

    # Wipe & replace.
    existing = (
        await db.execute(
            select(VoiceBusinessHours).where(
                VoiceBusinessHours.phone_number_id == payload.phone_number_id
            )
        )
    ).scalars().all()
    for row in existing:
        await db.delete(row)

    from datetime import time as _time

    def _parse_hm(s: str) -> _time:
        h, m = s.split(":")
        return _time(int(h), int(m))

    new_rows: List[VoiceBusinessHours] = []
    for item in payload.hours:
        r = VoiceBusinessHours(
            phone_number_id=payload.phone_number_id,
            day_of_week=item.day_of_week,
            open_time=_parse_hm(item.open_time),
            close_time=_parse_hm(item.close_time),
            timezone=item.timezone,
        )
        db.add(r)
        new_rows.append(r)
    await db.flush()
    return [
        BusinessHoursRead(
            id=r.id,
            phone_number_id=r.phone_number_id,
            day_of_week=r.day_of_week,
            open_time=r.open_time.strftime("%H:%M"),
            close_time=r.close_time.strftime("%H:%M"),
            timezone=r.timezone,
        )
        for r in new_rows
    ]
