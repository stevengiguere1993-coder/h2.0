"""Listes de référence du formulaire « Nouveau bon de travail ».

Un bon de travail INTERNE se rattache à un de NOS immeubles (compagnie →
immeuble → appartement). Le formulaire vit côté Construction, mais les
immeubles/logements sont des entités du pôle Gestion immobilière : il
tapait donc ``/immobilier/immeubles``, gardé par le volet
« immobilier ». Résultat : un gestionnaire Construction SANS ce volet
recevait un 403 silencieux et voyait « Aucun immeuble » (retour Phil
2026-07-20 — Olivier ne voyait rien, Phil owner voyait tout).

Ces endpoints exposent le STRICT MINIMUM nécessaire au formulaire (id,
nom, adresse ; id + numéro pour les logements) sur le routeur des bons,
ouvert à « construction OU immobilier » — comme le reste de la feature.
Aucune donnée financière ou locative n'y transite.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.permissions import visible_immeuble_ids
from app.models.immobilier import Immeuble, ImmeubleOwnership, Logement

router = APIRouter(prefix="/bons/refs", tags=["bons"])


class ImmeubleRef(BaseModel):
    id: int
    name: str
    address: str


class LogementRef(BaseModel):
    id: int
    numero: str


@router.get("/immeubles", response_model=List[ImmeubleRef])
async def list_immeubles_ref(
    db: DBSession,
    user: CurrentUser,
    entreprise_id: Optional[int] = None,
) -> List[ImmeubleRef]:
    """Immeubles actifs (optionnellement filtrés par compagnie
    propriétaire) pour le sélecteur du bon de travail."""
    q = select(Immeuble).where(Immeuble.is_active.is_(True))
    # Visibilité par affectation pour les employés (None = tout voir).
    visible = await visible_immeuble_ids(db, user)
    if visible is not None:
        q = q.where(Immeuble.id.in_(visible))
    if entreprise_id is not None:
        q = q.join(
            ImmeubleOwnership,
            ImmeubleOwnership.immeuble_id == Immeuble.id,
        ).where(ImmeubleOwnership.entreprise_id == int(entreprise_id))
    rows = (await db.execute(q.order_by(Immeuble.name.asc()))).scalars().all()
    return [
        ImmeubleRef(id=i.id, name=i.name, address=i.address or "")
        for i in rows
    ]


@router.get(
    "/immeubles/{immeuble_id}/logements", response_model=List[LogementRef]
)
async def list_logements_ref(
    immeuble_id: int, db: DBSession, user: CurrentUser
) -> List[LogementRef]:
    """Appartements d'un immeuble pour le sélecteur du bon de travail."""
    visible = await visible_immeuble_ids(db, user)
    if visible is not None and immeuble_id not in visible:
        return []
    rows = (
        await db.execute(
            select(Logement)
            .where(Logement.immeuble_id == immeuble_id)
            .order_by(Logement.numero.asc())
        )
    ).scalars().all()
    return [LogementRef(id=lg.id, numero=lg.numero or "") for lg in rows]
