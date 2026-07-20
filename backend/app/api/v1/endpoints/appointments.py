"""Schedule a prospect appointment — creates an AgendaEvent linked to
a ContactRequest and sends a confirmation email. The 24h reminder is
handled by the `appointment_reminders` cron.

    POST /api/v1/appointments   — schedule + notify
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import DBSession, RequireManager
from app.models.agenda_event import AgendaEvent
from app.models.contact_request import ContactRequest, ContactRequestStatus
from app.models.employe import Employe
from app.models.follow_up import FollowUp
from app.core.config import settings
from app.services.appointment_mail import (
    resolve_employe_email,
    send_appointment_assignee_invite,
    send_appointment_confirmation,
    send_appointment_owner_invite,
)


router = APIRouter(prefix="/appointments", tags=["appointments"])


class AppointmentCreate(BaseModel):
    contact_request_id: int
    title: str = Field(..., min_length=1, max_length=255)
    start_at: datetime
    end_at: datetime
    location: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    event_type: str = Field(default="visite", max_length=32)


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    start_at: datetime
    end_at: Optional[datetime]
    contact_request_id: Optional[int]
    assignee_id: Optional[int]
    event_type: str
    confirmation_sent_at: Optional[datetime] = None
    #: Rempli quand l'invitation calendrier de l'employé assigné N'A PAS
    #: pu partir (aucun courriel joignable) — affiché dans l'UI au lieu
    #: d'un échec silencieux (retour Phil 2026-07-20).
    assignee_invite_warning: Optional[str] = None


@router.post(
    "",
    response_model=AppointmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def schedule_appointment(
    data: AppointmentCreate,
    db: DBSession,
    user: RequireManager,
    bg: BackgroundTasks,
) -> AppointmentRead:
    if data.end_at <= data.start_at:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Plage horaire invalide."
        )
    prospect = (
        await db.execute(
            select(ContactRequest).where(
                ContactRequest.id == data.contact_request_id
            )
        )
    ).scalar_one_or_none()
    if prospect is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Prospect introuvable."
        )

    event = AgendaEvent(
        title=data.title.strip(),
        description=(data.description or None),
        location=(data.location or None),
        start_at=data.start_at,
        end_at=data.end_at,
        all_day=False,
        assignee_id=data.assignee_id,
        contact_request_id=data.contact_request_id,
        event_type=data.event_type,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)

    # Auto-transition vers "rdv_prevu" : planifier un RDV ne fait avancer
    # que les prospects ENCORE AVANT l'etape RDV (new, contacted). On NE
    # touche PAS a partir de "qualified" (= Soumission en preparation) ni
    # au-dela : ces fiches sont DEJA plus avancees que le RDV dans le
    # pipeline (new -> contacted -> rdv_prevu -> qualified -> quoted -> ...),
    # un RDV de suivi ne doit pas les faire RECULER vers "Rendez-vous prevu".
    if prospect.status in (
        ContactRequestStatus.NEW.value,
        ContactRequestStatus.CONTACTED.value,
    ):
        prospect.status = ContactRequestStatus.RDV_PREVU.value

    # Un RDV planifié remplace les relances automatiques : on suspend la
    # cadence de suivi en attente pour que le prospect ne s'affiche plus
    # « en retard ». Le responsable recevra plutôt une notification de
    # confirmation 48 h avant le RDV (cron follow_up_reminders).
    from app.services.follow_up import suspend_pending_followups

    rdv_label = data.start_at.strftime("%Y-%m-%d %H:%M")
    await suspend_pending_followups(
        db,
        subject_type="prospect",
        subject_id=prospect.id,
        note=f"RDV planifié le {rdv_label} — relances auto suspendues.",
    )
    # Trace dans le journal de suivi pour expliquer l'absence de relance.
    db.add(
        FollowUp(
            subject_type="prospect",
            subject_id=prospect.id,
            kind="auto",
            direction="outbound",
            outcome="scheduled",
            notes=(
                f"RDV planifié le {rdv_label}. "
                "Confirmation envoyée au responsable 48 h avant."
            ),
            performed_by_user_id=user.id,
            next_action_at=None,
            overdue_notified=True,
        )
    )
    await db.flush()

    # Fire the confirmation email in the background. Worst case the
    # send fails — the agenda event is still created and the cron will
    # try the 24h reminder as a fallback.
    async def _send_and_mark(
        prospect_id: int, event_id: int
    ) -> None:
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as fresh_db:
            pr = (
                await fresh_db.execute(
                    select(ContactRequest).where(
                        ContactRequest.id == prospect_id
                    )
                )
            ).scalar_one_or_none()
            ev = (
                await fresh_db.execute(
                    select(AgendaEvent).where(AgendaEvent.id == event_id)
                )
            ).scalar_one_or_none()
            if pr is None or ev is None:
                return
            ok = await send_appointment_confirmation(pr, ev)
            if ok:
                ev.confirmation_sent_at = datetime.now(timezone.utc)
                await fresh_db.commit()

    bg.add_task(_send_and_mark, prospect.id, event.id)

    # If an employee was assigned, send them an .ics calendar invite so
    # the RDV lands in their personal calendar.
    assignee_warning: Optional[str] = None
    if data.assignee_id is not None:
        # Vérif SYNCHRONE du courriel joignable (fiche employé, sinon
        # compte Kratos du même nom) : sans ça l'invitation échouait en
        # SILENCE et personne ne savait que l'employé n'avait rien reçu
        # (retour Phil 2026-07-20).
        emp_now = (
            await db.execute(
                select(Employe).where(Employe.id == data.assignee_id)
            )
        ).scalar_one_or_none()
        dest_now = (
            await resolve_employe_email(db, emp_now)
            if emp_now is not None
            else None
        )
        if emp_now is None:
            assignee_warning = "Employé assigné introuvable."
        elif not dest_now:
            assignee_warning = (
                f"{emp_now.full_name} n'a aucun courriel (ni sur sa fiche "
                "Employé, ni sur son compte) — l'invitation calendrier n'a "
                "pas pu être envoyée. Ajoute son courriel dans Employés."
            )

        async def _invite_assignee(assignee_id: int, event_id: int) -> None:
            from app.db.session import AsyncSessionLocal

            async with AsyncSessionLocal() as fresh_db:
                emp = (
                    await fresh_db.execute(
                        select(Employe).where(Employe.id == assignee_id)
                    )
                ).scalar_one_or_none()
                ev = (
                    await fresh_db.execute(
                        select(AgendaEvent).where(AgendaEvent.id == event_id)
                    )
                ).scalar_one_or_none()
                pr = (
                    await fresh_db.execute(
                        select(ContactRequest).where(
                            ContactRequest.id == ev.contact_request_id
                        )
                    )
                ).scalar_one_or_none() if ev and ev.contact_request_id else None
                if emp is None or ev is None:
                    return
                dest = await resolve_employe_email(fresh_db, emp)
                await send_appointment_assignee_invite(
                    emp, ev, pr, email_override=dest
                )

        bg.add_task(_invite_assignee, data.assignee_id, event.id)

    # Invitation calendrier vers l'adresse « agenda » du proprietaire :
    # a CHAQUE RDV, meme non assigne, pour qu'il atterrisse toujours
    # dans son agenda. On evite le doublon si le responsable assigne EST
    # deja cette adresse (il recoit alors l'invite via _invite_assignee).
    owner_email = (settings.appointment_owner_email or "").strip()
    if owner_email:
        async def _invite_owner(event_id: int, assignee_id: Optional[int]) -> None:
            from app.db.session import AsyncSessionLocal

            async with AsyncSessionLocal() as fresh_db:
                ev = (
                    await fresh_db.execute(
                        select(AgendaEvent).where(AgendaEvent.id == event_id)
                    )
                ).scalar_one_or_none()
                if ev is None:
                    return
                if assignee_id is not None:
                    emp = (
                        await fresh_db.execute(
                            select(Employe).where(Employe.id == assignee_id)
                        )
                    ).scalar_one_or_none()
                    if emp and (emp.email or "").strip().lower() == owner_email.lower():
                        return  # deja invite comme responsable assigne
                pr = (
                    await fresh_db.execute(
                        select(ContactRequest).where(
                            ContactRequest.id == ev.contact_request_id
                        )
                    )
                ).scalar_one_or_none() if ev.contact_request_id else None
                await send_appointment_owner_invite(owner_email, ev, pr)

        bg.add_task(_invite_owner, event.id, data.assignee_id)

    out = AppointmentRead.model_validate(event)
    out.assignee_invite_warning = assignee_warning
    return out


class AppointmentUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    location: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    event_type: Optional[str] = Field(default=None, max_length=32)


@router.patch("/{event_id}", response_model=AppointmentRead)
async def update_appointment(
    event_id: int,
    data: AppointmentUpdate,
    db: DBSession,
    user: RequireManager,
    bg: BackgroundTasks,
) -> AppointmentRead:
    """Modifier un RDV prospect existant. Restreint aux events liés
    a un ContactRequest pour éviter de toucher aux events agenda
    génériques par ce endpoint."""
    event = await db.get(AgendaEvent, event_id)
    if event is None or event.contact_request_id is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Rendez-vous introuvable."
        )

    old_assignee_id = event.assignee_id
    if data.start_at is not None:
        event.start_at = data.start_at
    if data.end_at is not None:
        event.end_at = data.end_at
    if event.end_at is not None and event.end_at <= event.start_at:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Plage horaire invalide."
        )
    if data.title is not None:
        event.title = data.title.strip()
    if data.location is not None:
        event.location = data.location.strip() or None
    if data.description is not None:
        event.description = data.description or None
    if data.event_type is not None:
        event.event_type = data.event_type
    if data.assignee_id is not None:
        event.assignee_id = data.assignee_id or None

    await db.flush()
    await db.refresh(event)

    # Réassignation à un nouvel employé → on lui envoie l'invitation
    # calendrier .ics + courriel (comme à la création), pour que le RDV
    # atterrisse dans SON agenda. On ne renvoie rien si l'assigné n'a
    # pas changé.
    patch_warning: Optional[str] = None
    if (
        event.assignee_id is not None
        and event.assignee_id != old_assignee_id
    ):
        emp_now = (
            await db.execute(
                select(Employe).where(Employe.id == event.assignee_id)
            )
        ).scalar_one_or_none()
        dest_now = (
            await resolve_employe_email(db, emp_now)
            if emp_now is not None
            else None
        )
        if emp_now is not None and not dest_now:
            patch_warning = (
                f"{emp_now.full_name} n'a aucun courriel (ni sur sa fiche "
                "Employé, ni sur son compte) — l'invitation calendrier n'a "
                "pas pu être envoyée. Ajoute son courriel dans Employés."
            )

        async def _invite_new_assignee(assignee_id: int, ev_id: int) -> None:
            from app.db.session import AsyncSessionLocal

            async with AsyncSessionLocal() as fresh_db:
                emp = (
                    await fresh_db.execute(
                        select(Employe).where(Employe.id == assignee_id)
                    )
                ).scalar_one_or_none()
                ev = (
                    await fresh_db.execute(
                        select(AgendaEvent).where(AgendaEvent.id == ev_id)
                    )
                ).scalar_one_or_none()
                pr = (
                    (
                        await fresh_db.execute(
                            select(ContactRequest).where(
                                ContactRequest.id == ev.contact_request_id
                            )
                        )
                    ).scalar_one_or_none()
                    if ev and ev.contact_request_id
                    else None
                )
                if emp is None or ev is None:
                    return
                dest = await resolve_employe_email(fresh_db, emp)
                await send_appointment_assignee_invite(
                    emp, ev, pr, email_override=dest
                )

        bg.add_task(_invite_new_assignee, event.assignee_id, event.id)

    out = AppointmentRead.model_validate(event)
    out.assignee_invite_warning = patch_warning
    return out


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_appointment(
    event_id: int,
    db: DBSession,
    user: RequireManager,
) -> Response:
    """Supprimer un RDV prospect. Restreint aux events liés a un
    ContactRequest."""
    event = await db.get(AgendaEvent, event_id)
    if event is None or event.contact_request_id is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Rendez-vous introuvable."
        )
    await db.delete(event)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{event_id}/resend-confirmation")
async def resend_confirmation(
    event_id: int,
    db: DBSession,
    user: RequireManager,
) -> dict:
    """Renvoie le courriel de confirmation du RDV au prospect, avec
    le .ics joint. Met a jour confirmation_sent_at en cas de succes."""
    event = await db.get(AgendaEvent, event_id)
    if event is None or event.contact_request_id is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Rendez-vous introuvable."
        )
    prospect = (
        await db.execute(
            select(ContactRequest).where(
                ContactRequest.id == event.contact_request_id
            )
        )
    ).scalar_one_or_none()
    if prospect is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Prospect introuvable."
        )
    ok = await send_appointment_confirmation(prospect, event)
    if not ok:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Envoi du courriel echoue (mailer non configure ou rejet).",
        )
    event.confirmation_sent_at = datetime.now(timezone.utc)
    await db.flush()
    return {"sent": True}
