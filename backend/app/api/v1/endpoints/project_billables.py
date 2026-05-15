"""Vue « à refacturer » par projet.

Liste toutes les sources potentielles de refacturation pour un projet
qui n'ont pas encore été versées sur une facture client. Sert à
alimenter l'onglet « À refacturer » de la page projet et le sélecteur
d'import dans le flux de création de facture.

Phase A : achats refacturables non facturés.
Phase B (à venir) : punches non facturés (heures × billing_rate).
Phase C (à venir) : factures de sous-traitants non refacturées.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.achat import Achat
from app.models.fournisseur import Fournisseur
from app.models.project import Project


router = APIRouter(prefix="/projects", tags=["project-billables"])


class BillableAchat(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reference: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    markup_percent: Optional[float] = None
    fournisseur_id: Optional[int] = None
    fournisseur_name: Optional[str] = None
    supplier_invoice_number: Optional[str] = None
    # Montant projeté qui sera facturé au client (cost × (1 + markup/100)).
    projected_billed_amount: float = 0.0


class BillablesSummary(BaseModel):
    achats: List[BillableAchat]
    total_cost: float
    total_projected: float
    count: int


@router.get(
    "/{project_id}/billables",
    response_model=BillablesSummary,
    summary="Liste tout ce qui reste à refacturer pour le projet",
)
async def list_billables(
    project_id: int, db: DBSession, _: CurrentUser
) -> BillablesSummary:
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    achats = (
        await db.execute(
            select(Achat)
            .where(Achat.project_id == project_id)
            .where(Achat.is_billable.is_(True))
            .where(Achat.invoiced_at.is_(None))
            .order_by(Achat.id.asc())
        )
    ).scalars().all()

    # Résolution des noms de fournisseurs en un seul round-trip.
    fourn_ids = {a.fournisseur_id for a in achats if a.fournisseur_id}
    fourn_names: dict[int, str] = {}
    if fourn_ids:
        rows = (
            await db.execute(
                select(Fournisseur.id, Fournisseur.name).where(
                    Fournisseur.id.in_(fourn_ids)
                )
            )
        ).all()
        fourn_names = {fid: name for fid, name in rows}

    items: List[BillableAchat] = []
    total_cost = 0.0
    total_projected = 0.0
    for a in achats:
        cost = float(a.amount or 0)
        markup = float(a.markup_percent or 0)
        projected = round(cost * (1 + markup / 100.0), 2)
        total_cost += cost
        total_projected += projected
        items.append(
            BillableAchat(
                id=a.id,
                reference=a.reference,
                description=a.description,
                amount=cost,
                markup_percent=markup if a.markup_percent is not None else None,
                fournisseur_id=a.fournisseur_id,
                fournisseur_name=fourn_names.get(a.fournisseur_id or 0),
                supplier_invoice_number=a.supplier_invoice_number,
                projected_billed_amount=projected,
            )
        )

    return BillablesSummary(
        achats=items,
        total_cost=round(total_cost, 2),
        total_projected=round(total_projected, 2),
        count=len(items),
    )
