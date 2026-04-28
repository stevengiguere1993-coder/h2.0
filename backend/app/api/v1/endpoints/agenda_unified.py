"""Vue agenda unifiée — fusionne events de scope + blocs opaques.

Quand l'utilisateur consulte l'agenda de son volet (Construction OU
Prospection), il doit voir :
1. Tous les events de SON volet en clair (titre, lieu, description).
2. Les events de l'AUTRE volet auxquels il est lié comme blocs
   opaques « Indisponible » (juste les heures, pas les détails).
3. Les blocs opaques externes (.ics Google/Outlook) — déjà gérés
   par /api/v1/calendar/busy.

Cet endpoint regroupe (1) et (2). Les blocs externes (3) sont
fetché·es séparément côté front (déjà en place).

GET /api/v1/agenda/unified?scope=prospection&from=2026-04-28&to=2026-05-05

+ Endpoint dédié POST /agenda/invite pour création avec assignation
à un autre user, qui déclenche notification cloche + email avec
lien de confirmation.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DBSession
from app.core.config import settings
from app.models.agenda_event import AgendaEvent
from app.models.employe import Employe
from app.models.user import User as UserModel

log = logging.getLogger(__name__)

router = APIRouter(prefix="/agenda", tags=["agenda"])


class UnifiedEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    location: Optional[str] = None
    description: Optional[str] = None
    start_at: datetime
    end_at: Optional[datetime] = None
    all_day: bool = False
    scope: str
    event_type: str
    project_id: Optional[int] = None
    lead_id: Optional[int] = None
    assignee_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    # True quand l'event appartient à un autre volet que celui demandé.
    # Le frontend l'affiche comme un bloc opaque « Indisponible ».
    is_opaque: bool = False


def _opaque(e: AgendaEvent) -> UnifiedEvent:
    """Convertit un event en bloc opaque — efface titre/desc/lieu."""
    return UnifiedEvent(
        id=e.id,
        title="Indisponible",
        location=None,
        description=None,
        start_at=e.start_at,
        end_at=e.end_at,
        all_day=e.all_day,
        scope=e.scope or "construction",
        event_type="busy",
        project_id=None,
        lead_id=None,
        assignee_id=e.assignee_id,
        assignee_user_id=e.assignee_user_id,
        is_opaque=True,
    )


def _full(e: AgendaEvent) -> UnifiedEvent:
    return UnifiedEvent(
        id=e.id,
        title=e.title,
        location=e.location,
        description=e.description,
        start_at=e.start_at,
        end_at=e.end_at,
        all_day=e.all_day,
        scope=e.scope or "construction",
        event_type=e.event_type or "chantier",
        project_id=e.project_id,
        lead_id=e.lead_id,
        assignee_id=e.assignee_id,
        assignee_user_id=e.assignee_user_id,
        is_opaque=False,
    )


@router.get("/unified", response_model=List[UnifiedEvent])
async def unified_agenda(
    db: DBSession,
    user: CurrentUser,
    scope: str = Query(
        ..., pattern="^(construction|prospection)$",
        description="Volet de la vue : events de ce scope en clair.",
    ),
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
    user_id: Optional[int] = Query(
        default=None,
        description="Si fourni, filtre aux events de cet utilisateur. "
        "Sinon, filtre à l'utilisateur courant. Owner/admin peut "
        "consulter l'agenda d'un autre user.",
    ),
) -> List[UnifiedEvent]:
    if to <= from_:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "`to` doit être > `from`."
        )

    target_user_id = user_id or user.id
    # Permission : un user peut voir son propre agenda. Owner/admin
    # peut voir celui des autres (utile pour la vue dispo équipe).
    if target_user_id != user.id and not user.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Permissions insuffisantes pour consulter cet agenda.",
        )

    # Trouve l'Employe correspondant (match email) pour résoudre
    # AgendaEvent.assignee_id (lien historique côté Construction).
    target_emp_id: Optional[int] = None
    target_user_email: Optional[str] = None
    if target_user_id == user.id:
        target_user_email = user.email
    else:
        from app.models.user import User as UserModel

        u = (
            await db.execute(
                select(UserModel).where(UserModel.id == target_user_id)
            )
        ).scalar_one_or_none()
        if u:
            target_user_email = u.email
    if target_user_email:
        emp = (
            await db.execute(
                select(Employe).where(
                    Employe.email == target_user_email
                )
            )
        ).scalar_one_or_none()
        if emp:
            target_emp_id = emp.id

    # Fenêtre temporelle : on prend tout event qui chevauche [from, to].
    # Un event chevauche si start_at < to ET (end_at > from OU end_at IS NULL).
    overlap = AgendaEvent.start_at < to
    end_filter = or_(
        AgendaEvent.end_at > from_,
        AgendaEvent.end_at.is_(None),
    )

    # Filtre user : événements assignés à ce user (via assignee_user_id)
    # OU à son Employe miroir (via assignee_id).
    user_filter_clauses = [AgendaEvent.assignee_user_id == target_user_id]
    if target_emp_id is not None:
        user_filter_clauses.append(AgendaEvent.assignee_id == target_emp_id)
    user_filter = or_(*user_filter_clauses)

    stmt = (
        select(AgendaEvent)
        .where(overlap, end_filter, user_filter)
        .order_by(AgendaEvent.start_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()

    out: List[UnifiedEvent] = []
    for e in rows:
        e_scope = e.scope or "construction"
        if e_scope == scope:
            out.append(_full(e))
        else:
            out.append(_opaque(e))
    return out


# ============== Création avec invitation ==============


class AgendaInviteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    location: Optional[str] = None
    start_at: datetime
    end_at: Optional[datetime] = None
    all_day: bool = False
    scope: str = Field(pattern="^(construction|prospection)$")
    event_type: str = "rdv"
    project_id: Optional[int] = None
    lead_id: Optional[int] = None
    assignee_user_id: int  # obligatoire pour cet endpoint
    send_email_invite: bool = True


class AgendaInviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    start_at: datetime
    end_at: Optional[datetime]
    assignee_user_id: int
    invitation_sent_at: Optional[datetime]
    invitation_confirmed_at: Optional[datetime]
    notification_id: Optional[int] = None


def _can_assign_others(user) -> bool:
    """Manager+ OU permission spéciale `can_assign_others`. Permet à
    un employé spécifique (ex: Zachary) de planifier sans être manager."""
    if user.has_min_role("manager"):
        return True
    return bool(getattr(user, "can_assign_others", False))


@router.post("/invite", response_model=AgendaInviteOut)
async def create_with_invite(
    data: AgendaInviteCreate,
    db: DBSession,
    user: CurrentUser,
) -> AgendaInviteOut:
    """Crée un RDV avec assignation à un autre user. Déclenche :
    1. Notification cloche pour l'assigné
    2. Email d'invitation avec lien de confirmation (si send_email_invite)

    Permission : manager+ OU user avec `can_assign_others=True`
    (cas Zachary).
    """
    if data.assignee_user_id != user.id and not _can_assign_others(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Tu n'as pas la permission d'assigner des RDV à d'autres "
            "utilisateurs. Demande à un manager ou owner.",
        )

    target = (
        await db.execute(
            select(UserModel).where(UserModel.id == data.assignee_user_id)
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(404, "Utilisateur cible introuvable.")
    if not target.is_active:
        raise HTTPException(
            400, "L'utilisateur cible est désactivé."
        )

    # Crée l'event
    event = AgendaEvent(
        title=data.title.strip(),
        description=data.description,
        location=data.location,
        start_at=data.start_at,
        end_at=data.end_at,
        all_day=data.all_day,
        scope=data.scope,
        event_type=data.event_type,
        project_id=data.project_id,
        lead_id=data.lead_id,
        assignee_user_id=data.assignee_user_id,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)

    # Notification cloche pour l'assigné
    notif_id: Optional[int] = None
    if data.assignee_user_id != user.id:
        from app.services.notifications import notify

        when = data.start_at.strftime("%-d %b %Y à %Hh%M")
        scope_label = (
            "Prospection" if data.scope == "prospection" else "Construction"
        )
        notif = await notify(
            db,
            user_id=data.assignee_user_id,
            kind="agenda_invitation",
            title=f"Nouveau RDV {scope_label} : {data.title}",
            body=f"{when}" + (
                f" · {data.location}" if data.location else ""
            )
            + f" · ajouté par {user.email}",
            href=(
                f"/{'prospection' if data.scope == 'prospection' else 'app'}"
                f"/agenda"
            ),
        )
        notif_id = notif.id

    # Email d'invitation avec lien token
    if data.send_email_invite and data.assignee_user_id != user.id:
        await _send_invitation_email(db, event, target, user)
        event.invitation_sent_at = datetime.now(timezone.utc)
        await db.flush()

    return AgendaInviteOut(
        id=event.id,
        title=event.title,
        start_at=event.start_at,
        end_at=event.end_at,
        assignee_user_id=event.assignee_user_id or 0,
        invitation_sent_at=event.invitation_sent_at,
        invitation_confirmed_at=event.invitation_confirmed_at,
        notification_id=notif_id,
    )


async def _ensure_invite_token(db, target: UserModel) -> str:
    """Génère un token agenda_invite_token persistant pour l'user
    s'il n'en a pas déjà un. Le token est réutilisé pour tous ses
    RDV — il authentifie « cette personne » sans login. Régénérable
    par l'utilisateur via les paramètres."""
    if target.agenda_invite_token:
        return target.agenda_invite_token
    target.agenda_invite_token = secrets.token_urlsafe(32)
    await db.flush()
    return target.agenda_invite_token


async def _send_invitation_email(
    db, event: AgendaEvent, target: UserModel, inviter
) -> None:
    """Envoie l'email d'invitation avec lien de confirmation."""
    if not target.email:
        return
    try:
        from app.integrations.email_graph import get_mailer

        mailer = get_mailer()
        if mailer is None:
            return
        token = await _ensure_invite_token(db, target)
        base = settings.frontend_url
        confirm_url = (
            f"{base}/agenda/confirm/{event.id}?token={token}"
        )
        when = event.start_at.strftime("%A %-d %B %Y à %Hh%M")
        html = (
            f"<p>Bonjour,</p>"
            f"<p><strong>{inviter.email}</strong> t'a assigné un "
            f"rendez-vous :</p>"
            f"<ul>"
            f"<li><strong>{event.title}</strong></li>"
            f"<li>{when}</li>"
            + (f"<li>Lieu : {event.location}</li>" if event.location else "")
            + f"</ul>"
            f"<p><a href=\"{confirm_url}\" style=\"display:inline-block;"
            f"padding:10px 20px;background:#10b981;color:#fff;"
            f"text-decoration:none;border-radius:6px;\">Confirmer "
            f"et ajouter à mon calendrier</a></p>"
            f"<p style=\"color:#666;font-size:12px;\">Tu peux aussi "
            f"voir tous tes RDV sur <a href=\"{base}/prospection/agenda\">"
            f"l'agenda Prospection</a> ou via l'abonnement iCal "
            f"(Paramètres → Connexions).</p>"
        )
        await mailer.send(
            to=[target.email],
            subject=f"RDV : {event.title}",
            html_body=html,
        )
    except Exception as exc:
        log.exception("agenda invitation email failed: %s", exc)


@router.get(
    "/confirm/{event_id}",
    summary="Lien public depuis l'email d'invitation. Marque le RDV "
    "comme confirmé sans demander de login.",
)
async def confirm_invitation(
    event_id: int,
    db: DBSession,
    token: str = Query(...),
) -> Response:
    """Confirme un RDV via token. Pas d'auth bearer, juste le token
    de l'utilisateur cible. Idempotent."""
    if not token:
        raise HTTPException(400, "Token manquant.")
    user = (
        await db.execute(
            select(UserModel).where(
                UserModel.agenda_invite_token == token
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(403, "Token invalide ou expiré.")
    event = await db.get(AgendaEvent, event_id)
    if event is None:
        raise HTTPException(404, "RDV introuvable.")
    if event.assignee_user_id != user.id:
        raise HTTPException(403, "Ce RDV ne t'appartient pas.")
    if event.invitation_confirmed_at is None:
        event.invitation_confirmed_at = datetime.now(timezone.utc)
        await db.flush()
    redirect_url = (
        f"{settings.frontend_url}/"
        f"{'prospection' if event.scope == 'prospection' else 'app'}"
        f"/agenda?confirmed={event_id}"
    )
    return Response(
        status_code=302,
        headers={"Location": redirect_url},
    )
