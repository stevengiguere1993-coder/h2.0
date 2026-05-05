"""Employee CRUD with auto-creation of a User account.

On reproduit l'API du generic CRUD utilisé pour les autres entités
business (list / get / create / update / delete) mais on intercepte
le POST pour créer en parallèle un User auth qui pourra se connecter
à l'app. Le mot de passe temporaire est « Horizon » et le flag
must_change_password est levé — l'employé sera forcé de le changer
au premier login.

Pourquoi pas un signal SQLAlchemy ? On veut absolument que la
création User échoue UNE TRANSACTION en cas d'email manquant ou
déjà pris, pour éviter d'avoir un employé orphelin sans compte.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.core.security import get_password_hash
from app.models.employe import Employe
from app.models.user import User, UserRole
from app.schemas.business import EmployeCreate, EmployeRead, EmployeUpdate


log = logging.getLogger(__name__)

router = APIRouter(prefix="/employes", tags=["employes"])


TEMPORARY_PASSWORD = "Horizon"


@router.get("", response_model=List[EmployeRead])
async def list_employes(
    db: DBSession,
    _: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    volet: Optional[str] = Query(
        None,
        description=(
            "Si fourni, ne retourne que les employés dont le compte "
            "User a accès à ce volet (ex. 'construction'). Les employés "
            "sans compte User (pas d'email) sont conservés — ce sont "
            "les ouvriers chantier sans accès portail."
        ),
    ),
) -> List[EmployeRead]:
    rows = (
        await db.execute(
            select(Employe).order_by(Employe.full_name.asc()).offset(skip).limit(limit)
        )
    ).scalars().all()

    if volet:
        # Filtre : on garde un employé si (a) il n'a pas d'email donc
        # pas de compte User (ouvrier chantier legacy) OU (b) son User
        # lié a accès au volet demandé. Les Users avec volets_json NULL
        # ont accès aux deux volets historiques (construction +
        # prospection) par backward compat — voir User.volets.
        emails = [e.email.strip().lower() for e in rows if e.email]
        users_by_email: dict[str, User] = {}
        if emails:
            users = (
                await db.execute(
                    select(User).where(User.email.in_(emails))
                )
            ).scalars().all()
            users_by_email = {u.email.strip().lower(): u for u in users}

        filtered: list[Employe] = []
        for e in rows:
            if not e.email:
                # Pas de compte portail → on conserve (legacy chantier).
                filtered.append(e)
                continue
            u = users_by_email.get(e.email.strip().lower())
            if u is None:
                # Email sans User correspondant → on conserve par
                # prudence (la création User a peut-être échoué).
                filtered.append(e)
                continue
            if volet in u.volets:
                filtered.append(e)
        rows = filtered

    return [EmployeRead.model_validate(r) for r in rows]


@router.get("/{item_id}", response_model=EmployeRead)
async def get_employe(
    item_id: int, db: DBSession, _: CurrentUser
) -> EmployeRead:
    e = (
        await db.execute(select(Employe).where(Employe.id == item_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employé introuvable.")
    return EmployeRead.model_validate(e)


class EmployeCreatedRead(EmployeRead):
    """Employe + drapeaux diagnostiques (pour informer le staff si
    l'auto-création de compte et/ou le courriel d'accueil ont
    effectivement eu lieu)."""

    user_created: bool = False
    welcome_email_sent: bool = False
    welcome_email_error: Optional[str] = None


@router.post(
    "",
    response_model=EmployeCreatedRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crée un employé + son compte utilisateur (mot de passe temporaire)",
)
async def create_employe(
    data: EmployeCreate, db: DBSession, _: RequireManager
) -> EmployeCreatedRead:
    e = Employe(**data.model_dump(exclude_unset=True))
    db.add(e)
    await db.flush()
    await db.refresh(e)

    user_created = False
    welcome_email_sent = False
    welcome_email_error: Optional[str] = None

    if e.email:
        # Un User existe peut-être déjà pour ce courriel (le proprio
        # créé en CLI, ou un employé re-créé). Dans ce cas on n'écrase
        # pas — on laisse l'employeur réinitialiser le mdp manuellement
        # depuis /app/utilisateurs si nécessaire.
        existing = (
            await db.execute(select(User).where(User.email == e.email))
        ).scalar_one_or_none()
        if existing is None:
            u = User(
                email=e.email,
                hashed_password=get_password_hash(TEMPORARY_PASSWORD),
                is_active=True,
                is_admin=False,
                role=UserRole.EMPLOYEE.value,
                must_change_password=True,
            )
            db.add(u)
            await db.flush()
            user_created = True

            # Courriel d'accueil avec mdp temporaire "Horizon".
            try:
                from app.services.welcome_email import send_welcome_email

                welcome_email_sent = await send_welcome_email(
                    to_email=e.email,
                    temporary_password=TEMPORARY_PASSWORD,
                    full_name=e.full_name,
                    role=UserRole.EMPLOYEE.value,
                )
                if not welcome_email_sent:
                    welcome_email_error = (
                        "Mailer non disponible (Azure Graph non "
                        "configuré ou courriel invalide)."
                    )
            except Exception as exc:
                log.exception("welcome email failed: %s", exc)
                welcome_email_error = f"Erreur mailer : {exc}"
        else:
            welcome_email_error = (
                "Un compte utilisateur existe déjà pour ce courriel — "
                "aucun mot de passe temporaire créé, aucun courriel "
                "envoyé. Utilise Paramètres → Utilisateurs & rôles "
                "pour réinitialiser le mdp manuellement."
            )

    out = EmployeCreatedRead.model_validate(e)
    out.user_created = user_created
    out.welcome_email_sent = welcome_email_sent
    out.welcome_email_error = welcome_email_error
    return out


@router.patch("/{item_id}", response_model=EmployeRead)
async def update_employe(
    item_id: int,
    data: EmployeUpdate,
    db: DBSession,
    _: RequireManager,
) -> EmployeRead:
    e = (
        await db.execute(select(Employe).where(Employe.id == item_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employé introuvable.")
    was_active = bool(e.active)
    patch = data.model_dump(exclude_unset=True)
    for field, value in patch.items():
        setattr(e, field, value)
    await db.flush()
    # Détection désactivation : si on passe de actif → inactif ET que
    # l'employé avait des assignations futures (phase, tâche, agenda),
    # on avertit les managers pour qu'ils réassignent avant que les
    # travaux ne soient affectés. Idempotent : l'alerte n'est envoyée
    # qu'une seule fois, à la transition.
    if was_active and "active" in patch and not bool(patch["active"]):
        from datetime import date as _date, datetime as _dt, timezone as _tz

        from app.models.agenda_event import AgendaEvent
        from app.models.project_assignees import (
            ProjectPhaseAssignee,
            ProjectTaskAssignee,
        )
        from app.models.project_phase import ProjectPhase
        from app.models.project_task import ProjectTask
        from app.services.notifications import notify_role

        today = _date.today()
        now_utc = _dt.now(_tz.utc)
        # Phases futures (fin ≥ aujourd'hui)
        phase_ids = (
            await db.execute(
                select(ProjectPhase.id).where(
                    ProjectPhase.assignee_employe_id == e.id,
                    ProjectPhase.start_date.is_not(None),
                )
            )
        ).all()
        joined_phase_ids = (
            await db.execute(
                select(ProjectPhaseAssignee.phase_id).where(
                    ProjectPhaseAssignee.employe_id == e.id
                )
            )
        ).all()
        has_future_phase = bool(phase_ids or joined_phase_ids)
        open_task_count = (
            await db.execute(
                select(ProjectTask.id).where(
                    ProjectTask.assignee_id == e.id,
                    ProjectTask.done.is_(False),
                )
            )
        ).all()
        joined_task_count = (
            await db.execute(
                select(ProjectTaskAssignee.task_id)
                .join(
                    ProjectTask,
                    ProjectTask.id == ProjectTaskAssignee.task_id,
                )
                .where(
                    ProjectTaskAssignee.employe_id == e.id,
                    ProjectTask.done.is_(False),
                )
            )
        ).all()
        has_open_task = bool(open_task_count or joined_task_count)
        future_events = (
            await db.execute(
                select(AgendaEvent.id).where(
                    AgendaEvent.assignee_id == e.id,
                    AgendaEvent.start_at >= now_utc,
                )
            )
        ).all()
        has_future_event = bool(future_events)
        if has_future_phase or has_open_task or has_future_event:
            pieces: list[str] = []
            if has_future_phase:
                pieces.append("des phases de chantier")
            if has_open_task:
                pieces.append("des tâches ouvertes")
            if has_future_event:
                pieces.append("des événements d'agenda")
            await notify_role(
                db,
                min_role="manager",
                kind="employe.deactivated_with_assignments",
                title=(
                    f"{e.full_name} désactivé avec assignations en cours"
                ),
                body=(
                    f"{e.full_name} vient d'être désactivé mais avait "
                    f"encore {', '.join(pieces)}. Pense à les réaffecter "
                    f"depuis /app/assignations. (ref: emp-{e.id}-"
                    f"{today.isoformat()})"
                ),
                href="/app/assignations",
            )
    await db.refresh(e)
    return EmployeRead.model_validate(e)


@router.delete(
    "/{item_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_employe(
    item_id: int, db: DBSession, _: RequireManager
) -> None:
    e = (
        await db.execute(select(Employe).where(Employe.id == item_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employé introuvable.")
    await db.delete(e)
    await db.flush()
