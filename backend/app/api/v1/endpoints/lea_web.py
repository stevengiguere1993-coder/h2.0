"""Léa-Web — chat texte public sur le site, alimenté par la même IA
secrétaire (app.integrations.voice.secretary). Réutilise tous les
intents et actions du téléphone : information, intake_construction,
propose_slots, book_slot.

Pas d'authentification : on identifie chaque conversation par un
`token` UUID stocké côté browser (localStorage). Les sessions
restent persistantes au refresh ou changement de page.

Endpoints publics :
  POST /api/v1/lea-web/start         → crée session + greeting
  POST /api/v1/lea-web/{token}/say   → envoie un message, reçoit réponse
  GET  /api/v1/lea-web/{token}       → état + historique
  POST /api/v1/lea-web/{token}/book  → confirme un slot proposé
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.integrations.voice.secretary import (
    SecretaryDecision,
    decide_initial_greeting,
    decide_next_turn,
)
from app.models.lea_chat import LeaChatMessage, LeaChatSession

log = logging.getLogger(__name__)


router = APIRouter(prefix="/lea-web", tags=["lea-web"])


# Rate limit anti-abus : max 30 msg / session / 24h (anti-spam)
MAX_MESSAGES_PER_SESSION = 100


class StartRequest(BaseModel):
    lang: str = Field(default="fr-CA", max_length=8)
    landing_page: Optional[str] = Field(default=None, max_length=500)


class MessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class BookRequest(BaseModel):
    chosen_slot_index: int = Field(..., ge=0, le=9)


class ChatMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: str
    text: str
    created_at: datetime
    meta_json: Optional[str] = None


class ChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    token: str
    lang: str
    visitor_name: Optional[str]
    visitor_email: Optional[str]
    visitor_phone: Optional[str]
    contact_request_id: Optional[int]
    booked_event_id: Optional[int]
    messages: List[ChatMessage]


def _load_state(session: LeaChatSession) -> dict:
    if not session.session_state:
        return {}
    try:
        return json.loads(session.session_state) or {}
    except Exception:
        return {}


def _save_state(session: LeaChatSession, state: dict) -> None:
    session.session_state = json.dumps(state, ensure_ascii=False)


async def _load_session_or_404(
    db: AsyncSession, token: str
) -> LeaChatSession:
    if not token or len(token) < 16:
        raise HTTPException(status_code=404, detail="session_invalid")
    s = (
        await db.execute(
            select(LeaChatSession).where(LeaChatSession.token == token)
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    return s


async def _load_messages(
    db: AsyncSession, session_id: int
) -> List[LeaChatMessage]:
    return (
        await db.execute(
            select(LeaChatMessage)
            .where(LeaChatMessage.session_id == session_id)
            .order_by(LeaChatMessage.created_at.asc(), LeaChatMessage.id.asc())
        )
    ).scalars().all()


@router.post(
    "/start",
    response_model=ChatSessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="(Public) Démarre une session chat Léa-Web",
)
async def start_session(
    payload: StartRequest, request: Request, db: DBSession
) -> ChatSessionRead:
    token = secrets.token_urlsafe(32)
    lang = payload.lang if payload.lang in ("fr-CA", "en-US") else "fr-CA"
    ua = (request.headers.get("user-agent") or "")[:500]
    s = LeaChatSession(
        token=token,
        lang=lang,
        landing_page=payload.landing_page,
        user_agent=ua,
    )
    db.add(s)
    await db.flush()

    # Greeting initial (identique au téléphone — phrase fixe, pas
    # d'appel IA pour gagner ~1 sec de latence au mount du widget).
    greeting = await decide_initial_greeting(lang=lang)
    msg = LeaChatMessage(
        session_id=s.id,
        role="assistant",
        text=greeting.say,
        meta_json=json.dumps({"intent": greeting.intent}),
    )
    db.add(msg)
    await db.flush()

    msgs = await _load_messages(db, s.id)
    return ChatSessionRead(
        token=s.token,
        lang=s.lang,
        visitor_name=s.visitor_name,
        visitor_email=s.visitor_email,
        visitor_phone=s.visitor_phone,
        contact_request_id=s.contact_request_id,
        booked_event_id=s.booked_event_id,
        messages=[ChatMessage.model_validate(m) for m in msgs],
    )


@router.get(
    "/{token}",
    response_model=ChatSessionRead,
    summary="(Public) État + historique d'une session",
)
async def get_session(token: str, db: DBSession) -> ChatSessionRead:
    s = await _load_session_or_404(db, token)
    msgs = await _load_messages(db, s.id)
    return ChatSessionRead(
        token=s.token,
        lang=s.lang,
        visitor_name=s.visitor_name,
        visitor_email=s.visitor_email,
        visitor_phone=s.visitor_phone,
        contact_request_id=s.contact_request_id,
        booked_event_id=s.booked_event_id,
        messages=[ChatMessage.model_validate(m) for m in msgs],
    )


@router.post(
    "/{token}/say",
    response_model=ChatSessionRead,
    summary="(Public) Envoie un message, reçoit la réponse de Léa",
)
async def post_message(
    token: str, payload: MessageRequest, db: DBSession
) -> ChatSessionRead:
    s = await _load_session_or_404(db, token)

    # Garde-fou anti-spam.
    count = (
        await db.execute(
            select(LeaChatMessage)
            .where(LeaChatMessage.session_id == s.id)
        )
    ).scalars().all()
    if len(count) >= MAX_MESSAGES_PER_SESSION:
        raise HTTPException(
            status_code=429,
            detail="Trop de messages dans cette session.",
        )

    # 1. Persiste le tour user
    user_msg = LeaChatMessage(
        session_id=s.id, role="user", text=payload.text.strip()[:2000]
    )
    db.add(user_msg)
    await db.flush()

    # 2. Construit l'historique pour Léa (même format que le téléphone)
    all_msgs = await _load_messages(db, s.id)
    history = [(m.role, m.text) for m in all_msgs if m.role in ("user", "assistant")]
    turn_count = len(history)

    # 3. Appel IA (cascade Gemini → Claude → Groq via app.integrations.ai)
    # On lui passe les coordonnées visiteur déjà collectées en
    # identity_context pour qu'elle adapte son discours.
    state = _load_state(s)
    proposed_slots = state.get("proposed_slots") or []
    intake_data = state.get("intake_data") or {}
    identity_ctx = _build_identity_ctx(s, intake_data, proposed_slots)

    # Pas de caller_e164 — c'est du chat web.
    decision = await decide_next_turn(
        history=history,
        current_turn_count=turn_count,
        caller_e164="web-chat",
        identity_context=identity_ctx,
    )

    # 4. Mise à jour de la session selon la décision
    s.last_active_at = datetime.now(timezone.utc)
    if decision.lang in ("fr-CA", "en-US"):
        s.lang = decision.lang
    # Coordonnées visiteur — Léa les capture progressivement
    if decision.lead_name and not s.visitor_name:
        s.visitor_name = decision.lead_name[:255]
    if decision.lead_callback_phone and not s.visitor_phone:
        s.visitor_phone = decision.lead_callback_phone[:50]
    # Merge intake_data accumulée
    if decision.intake_data:
        merged = dict(intake_data)
        merged.update(decision.intake_data)
        intake_data = merged
        if merged.get("email") and not s.visitor_email:
            s.visitor_email = merged["email"][:320]
        state["intake_data"] = intake_data
        _save_state(s, state)

    # 5. Dispatch action — pour Léa-Web, on traduit certaines actions
    # téléphoniques en équivalent texte :
    #   - transfer_*       → on dit « un agent vous contactera »
    #   - intake_complete  → crée ContactRequest + courriel validation
    #   - propose_slots    → cherche les créneaux + on les annonce
    #   - book_slot        → crée AgendaEvent + confirme
    #   - callback         → crée ContactRequest pour rappel manuel
    #   - end_spam         → ferme la session poliment
    assistant_text = decision.say
    meta = {
        "intent": decision.intent,
        "next_action": decision.next_action,
    }

    if decision.next_action == "propose_slots":
        slots = await _propose_slots_web(db, session=s, intake_data=intake_data)
        if slots:
            state = _load_state(s)
            state["proposed_slots"] = slots
            state["intake_data"] = intake_data
            _save_state(s, state)
            assistant_text = _format_slots_text(slots, lang=s.lang)
            meta["proposed_slots"] = slots
        else:
            assistant_text = (
                "Désolée, aucune disponibilité cette semaine. Notre équipe "
                "vous contactera sous peu pour fixer un rendez-vous."
                if s.lang.startswith("fr")
                else "Sorry, no availability this week. Our team will "
                "reach out shortly to schedule a visit."
            )
            await _create_lead_for_chat(db, session=s, intake_data=intake_data)

    elif decision.next_action == "book_slot":
        idx = decision.chosen_slot_index
        if idx is None or not proposed_slots:
            assistant_text = (
                "Je n'ai pas compris quel créneau choisir, "
                "pouvez-vous préciser le numéro ?"
                if s.lang.startswith("fr")
                else "I didn't catch which slot to pick, can you "
                "specify the number?"
            )
        else:
            booked = await _book_slot_for_chat(
                db,
                session=s,
                intake_data=intake_data,
                chosen_index=idx,
            )
            if booked:
                assistant_text = decision.say
                meta["booked_event_id"] = s.booked_event_id
            else:
                assistant_text = (
                    "Ce créneau vient d'être pris par quelqu'un d'autre. "
                    "Voulez-vous que je vous en propose d'autres ?"
                    if s.lang.startswith("fr")
                    else "That slot was just taken by someone else. "
                    "Want me to suggest others?"
                )

    elif decision.next_action == "intake_complete":
        await _create_lead_for_chat(db, session=s, intake_data=intake_data)

    elif decision.next_action == "callback":
        await _create_lead_for_chat(db, session=s, intake_data=intake_data)

    elif decision.next_action in ("transfer", "transfer_emergency", "transfer_project_lead"):
        # En chat web on ne transfère pas — on capture en callback
        # avec une note explicite pour le staff.
        assistant_text = (
            "Je transmets votre demande à un agent qui vous rappellera "
            "très rapidement."
            if s.lang.startswith("fr")
            else "I'm forwarding your request to an agent who will call "
            "you back shortly."
        )
        await _create_lead_for_chat(db, session=s, intake_data=intake_data)

    elif decision.next_action == "end_spam":
        # Ferme la conversation poliment.
        pass

    # 6. Persiste la réponse assistant
    assistant_msg = LeaChatMessage(
        session_id=s.id,
        role="assistant",
        text=assistant_text[:5000],
        meta_json=json.dumps(meta, ensure_ascii=False),
    )
    db.add(assistant_msg)
    await db.flush()

    # 7. Renvoie tout l'état mis à jour pour le widget
    msgs = await _load_messages(db, s.id)
    return ChatSessionRead(
        token=s.token,
        lang=s.lang,
        visitor_name=s.visitor_name,
        visitor_email=s.visitor_email,
        visitor_phone=s.visitor_phone,
        contact_request_id=s.contact_request_id,
        booked_event_id=s.booked_event_id,
        messages=[ChatMessage.model_validate(m) for m in msgs],
    )


@router.post(
    "/{token}/book",
    response_model=ChatSessionRead,
    summary="(Public) Confirme un slot proposé via les boutons UI",
)
async def book_slot(
    token: str, payload: BookRequest, db: DBSession
) -> ChatSessionRead:
    """Endpoint alternatif au « book_slot » côté Léa : permet à l'UI
    web de booker directement un slot via un bouton « Choisir ce
    créneau » sans devoir passer par le langage naturel."""
    s = await _load_session_or_404(db, token)
    state = _load_state(s)
    intake_data = state.get("intake_data") or {}
    booked = await _book_slot_for_chat(
        db,
        session=s,
        intake_data=intake_data,
        chosen_index=payload.chosen_slot_index,
    )
    if not booked:
        raise HTTPException(
            status_code=409,
            detail="Ce créneau n'est plus disponible.",
        )
    # Ajoute un message confirmation
    proposed = state.get("proposed_slots") or []
    chosen = proposed[payload.chosen_slot_index] if 0 <= payload.chosen_slot_index < len(proposed) else None
    if chosen:
        dt = datetime.fromisoformat(chosen["start_at"])
        confirm_text = _human_confirmation_text(dt, lang=s.lang)
    else:
        confirm_text = (
            "Rendez-vous confirmé."
            if s.lang.startswith("fr")
            else "Appointment confirmed."
        )
    db.add(
        LeaChatMessage(
            session_id=s.id,
            role="assistant",
            text=confirm_text,
            meta_json=json.dumps({"booked_event_id": s.booked_event_id}),
        )
    )
    await db.flush()

    msgs = await _load_messages(db, s.id)
    return ChatSessionRead(
        token=s.token,
        lang=s.lang,
        visitor_name=s.visitor_name,
        visitor_email=s.visitor_email,
        visitor_phone=s.visitor_phone,
        contact_request_id=s.contact_request_id,
        booked_event_id=s.booked_event_id,
        messages=[ChatMessage.model_validate(m) for m in msgs],
    )


# ─── Helpers internes ────────────────────────────────────────────


def _build_identity_ctx(
    session: LeaChatSession,
    intake_data: dict,
    proposed_slots: list,
) -> Optional[str]:
    bits: list[str] = ["[Session chat web — pas de téléphone]"]
    if session.visitor_name:
        bits.append(f"Nom visiteur : {session.visitor_name}")
    if session.visitor_email:
        bits.append(f"Email visiteur : {session.visitor_email}")
    if session.visitor_phone:
        bits.append(f"Téléphone visiteur : {session.visitor_phone}")
    if intake_data:
        for k, v in intake_data.items():
            if k != "proposed_slots":
                bits.append(f"Intake {k} : {v}")
    if proposed_slots:
        bits.append(f"Créneaux déjà proposés : {len(proposed_slots)} options ({proposed_slots})")
    if session.landing_page:
        bits.append(f"Page d'origine : {session.landing_page}")
    return "\n".join(bits) if len(bits) > 1 else None


_FR_WEEKDAYS_WEB = [
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"
]
_FR_MONTHS_WEB = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _format_slots_text(slots: list[dict], *, lang: str) -> str:
    if not slots:
        return ""
    lines = []
    for i, s in enumerate(slots, 1):
        dt = datetime.fromisoformat(s["start_at"])
        if lang.startswith("fr"):
            day = _FR_WEEKDAYS_WEB[dt.weekday()]
            hour = dt.strftime("%-Hh%M" if dt.minute else "%-Hh")
            lines.append(f"  {i}) {day} {dt.day} {_FR_MONTHS_WEB[dt.month-1]} à {hour}")
        else:
            lines.append(f"  {i}) {dt.strftime('%A %B %d at %I:%M %p')}")
    listing = "\n".join(lines)
    if lang.startswith("fr"):
        return (
            "Voici les disponibilités pour une visite d'évaluation :\n"
            + listing
            + "\n\nClique sur un créneau pour le réserver, ou écris-moi "
            "ton choix."
        )
    return (
        "Here are the available slots:\n"
        + listing
        + "\n\nClick a slot to book it, or type your choice."
    )


def _human_confirmation_text(dt: datetime, *, lang: str) -> str:
    if lang.startswith("fr"):
        day = _FR_WEEKDAYS_WEB[dt.weekday()]
        month = _FR_MONTHS_WEB[dt.month - 1]
        hour = dt.strftime("%-Hh%M" if dt.minute else "%-Hh")
        return (
            f"✅ Rendez-vous confirmé pour {day} {dt.day} {month} à {hour}. "
            f"Vous recevrez un courriel de confirmation. Merci !"
        )
    return (
        f"✅ Appointment confirmed for {dt.strftime('%A %B %d at %I:%M %p')}. "
        "You'll receive a confirmation email. Thanks!"
    )


async def _propose_slots_web(
    db: AsyncSession, *, session: LeaChatSession, intake_data: dict
) -> list[dict]:
    """Identique à _propose_appointment_slots côté téléphone."""
    from app.models.appointment_type import AppointmentType
    from app.services.agenda_slot_finder import find_available_slots

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
    return out


async def _create_lead_for_chat(
    db: AsyncSession, *, session: LeaChatSession, intake_data: dict
) -> Optional[int]:
    """Crée un ContactRequest depuis les infos chat. Idempotent."""
    import secrets as _sec

    from app.models.contact_request import (
        ContactRequest,
        ContactRequestStatus,
        ProjectType,
    )

    if session.contact_request_id is not None:
        return session.contact_request_id

    name = (session.visitor_name or "Visiteur web").strip()[:255]
    phone = (session.visitor_phone or "").strip()[:50] or None
    if session.visitor_email:
        email = session.visitor_email.strip()[:320]
    else:
        email = f"chat-{session.token[:16]}@chat.local"

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

    bits = ["Demande captée par Léa via le chat du site web.", ""]
    labels = {
        "type_travaux": "Type de travaux",
        "adresse": "Adresse",
        "echeancier": "Échéancier",
        "budget": "Budget",
        "best_callback_time": "Meilleur moment de rappel",
    }
    for key, label in labels.items():
        v = (intake_data or {}).get(key)
        if v:
            bits.append(f"- {label} : {v}")
    if session.landing_page:
        bits.append(f"- Page d'origine : {session.landing_page}")
    message = "\n".join(bits)

    token = _sec.token_urlsafe(32)
    cr = ContactRequest(
        name=name,
        email=email,
        phone=phone,
        address=(intake_data or {}).get("adresse"),
        project_type=project_type,
        budget_range=(intake_data or {}).get("budget"),
        message=message[:5000],
        locale="fr" if session.lang.startswith("fr") else "en",
        source="lea_chat_web",
        gdpr_consent=True,
        marketing_consent=False,
        status=ContactRequestStatus.NEW.value,
        intake_data=json.dumps(intake_data or {}, ensure_ascii=False),
        validation_token=token,
    )
    db.add(cr)
    await db.flush()
    session.contact_request_id = cr.id
    await db.flush()
    return cr.id


async def _book_slot_for_chat(
    db: AsyncSession,
    *,
    session: LeaChatSession,
    intake_data: dict,
    chosen_index: int,
) -> bool:
    """Crée l'AgendaEvent depuis le slot choisi. Re-vérifie la dispo."""
    state = _load_state(session)
    proposed = state.get("proposed_slots") or []
    if not (0 <= chosen_index < len(proposed)):
        return False
    chosen = proposed[chosen_index]

    cr_id = session.contact_request_id
    if cr_id is None:
        cr_id = await _create_lead_for_chat(db, session=session, intake_data=intake_data)

    from app.models.agenda_event import AgendaEvent
    from app.models.appointment_type import AppointmentType
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
            "Web chat slot no longer available (conflicts: %s)",
            recheck.conflicts,
        )
        return False

    title = f"Évaluation soumission — {session.visitor_name or 'Visiteur web'}"[:255]
    event = AgendaEvent(
        title=title,
        description=(
            "RV pris via le chat Léa-Web.\n"
            f"Email : {session.visitor_email or '—'}\n"
            f"Téléphone : {session.visitor_phone or '—'}\n"
            f"Type travaux : {intake_data.get('type_travaux') or '—'}\n"
            f"Adresse : {intake_data.get('adresse') or '—'}\n"
            f"Budget : {intake_data.get('budget') or '—'}\n"
            f"Échéancier : {intake_data.get('echeancier') or '—'}"
        ),
        location=intake_data.get("adresse") or None,
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
    session.contact_request_id = cr_id
    session.booked_event_id = event.id
    await db.flush()
    return True
