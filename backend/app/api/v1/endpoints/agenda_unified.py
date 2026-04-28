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
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DBSession
from app.models.agenda_event import AgendaEvent
from app.models.employe import Employe

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
