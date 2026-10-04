"""Achats côté app mobile employé.

Un employé ne doit PAS voir les achats de la compagnie dans l'app
mobile (retour Steven 2026-10-04) : seul son propre dernier achat y
est visible. La liste complète reste sur le site (/app/achats).
"""

from typing import Optional

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.achat import Achat
from app.schemas.business import AchatRead


router = APIRouter(prefix="/achats", tags=["achats-mobile"])


@router.get(
    "/mobile/mon-dernier",
    summary="Dernier achat saisi par l'utilisateur courant (app mobile)",
)
async def mon_dernier_achat(
    db: DBSession, current_user: CurrentUser
) -> Optional[AchatRead]:
    achat = (
        await db.execute(
            select(Achat)
            .where(Achat.created_by_user_id == current_user.id)
            .order_by(Achat.created_at.desc(), Achat.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if achat is None:
        return None
    return AchatRead.model_validate(achat)
