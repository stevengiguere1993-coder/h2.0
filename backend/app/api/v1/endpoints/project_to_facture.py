"""Create a Facture from a Project.

Pre-fills client, pulls the Project description, and optionally
seeds the line items from the project's approved (or all) punches —
grouped by employee × hourly_rate.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.achat import Achat
from app.models.employe import Employe
from app.models.facture import Facture, FactureStatus
from app.models.facture_item import FactureItem
from app.models.project import Project
from app.models.punch import Punch
from app.models.soumission import Soumission, SoumissionStatus
from app.models.soumission_item import SoumissionItem
from app.schemas.business import FactureRead


router = APIRouter(prefix="/projects", tags=["project-to-facture"])


class ConvertToFactureRequest(BaseModel):
    include_soumission: bool = Field(
        default=False,
        description=(
            "Seed line items from the accepted soumission linked to "
            "this project (prix fixe)."
        ),
    )
    soumission_percentage: int = Field(
        default=100, ge=1, le=100,
        description=(
            "Percentage of the soumission to invoice — supports progress "
            "billing (ex. 30% acompte, 50% mi-projet, 20% livraison)."
        ),
    )
    include_hours: bool = Field(
        default=True,
        description="Seed line items from the punched hours (T&M).",
    )
    only_approved: bool = Field(
        default=True,
        description="Only include approved punches.",
    )
    include_achats: bool = Field(
        default=False,
        description="Seed line items from the Achats linked to this project.",
    )
    due_in_days: Optional[int] = Field(
        default=30, ge=0, le=365,
        description="Days from today to the invoice due date.",
    )


def _build_ref() -> str:
    d = datetime.now(timezone.utc)
    return (
        f"FAC-{d.year}{d.month:02d}{d.day:02d}-"
        f"{d.hour:02d}{d.minute:02d}{d.second:02d}"
    )


@router.post(
    "/{project_id}/convert-to-facture",
    response_model=FactureRead,
    summary="Create a Facture from a Project (seeds line items from hours)",
)
async def convert_project_to_facture(
    project_id: int,
    data: ConvertToFactureRequest,
    db: DBSession,
    _: CurrentUser,
) -> FactureRead:
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    due_at = None
    if data.due_in_days is not None:
        due_at = datetime.now(timezone.utc) + timedelta(days=data.due_in_days)

    facture = Facture(
        reference=_build_ref(),
        client_id=project.client_id,
        project_id=project.id,
        status=FactureStatus.DRAFT.value,
        issued_at=datetime.now(timezone.utc),
        due_at=due_at,
    )
    db.add(facture)
    await db.flush()

    pos = 0

    # 1) Prix fixe — items de la soumission acceptée liée au projet.
    if data.include_soumission and project.soumission_id:
        sm = (
            await db.execute(
                select(Soumission).where(Soumission.id == project.soumission_id)
            )
        ).scalar_one_or_none()
        if sm is not None and sm.status in (
            SoumissionStatus.ACCEPTED.value,
            SoumissionStatus.SENT.value,
        ):
            sm_items = (
                await db.execute(
                    select(SoumissionItem)
                    .where(SoumissionItem.soumission_id == sm.id)
                    .order_by(SoumissionItem.position.asc(), SoumissionItem.id.asc())
                )
            ).scalars().all()
            pct = max(1, min(100, int(data.soumission_percentage)))
            ratio = pct / 100.0
            prefix = f"{pct}% — " if pct != 100 else ""
            for it in sm_items:
                qty = float(it.quantity)
                unit_price = round(float(it.unit_price) * ratio, 2)
                line_total = round(qty * unit_price, 2)
                db.add(
                    FactureItem(
                        facture_id=facture.id,
                        position=pos,
                        description=f"{prefix}{it.description}",
                        unit=it.unit,
                        quantity=qty,
                        unit_price=unit_price,
                        total=line_total,
                    )
                )
                pos += 1

    # 2) T&M — heures punchées approuvées x taux horaire, groupées par
    #    (employé, taux).
    if data.include_hours:
        stmt = select(Punch).where(Punch.project_id == project_id)
        if data.only_approved:
            stmt = stmt.where(Punch.approved.is_(True))
        stmt = stmt.where(Punch.hours.is_not(None))
        punches = (await db.execute(stmt)).scalars().all()

        if punches:
            emp_ids = {p.employe_id for p in punches}
            emps = {
                e.id: e
                for e in (
                    await db.execute(
                        select(Employe).where(Employe.id.in_(emp_ids))
                    )
                ).scalars().all()
            }

            buckets: dict[tuple[int, float], float] = {}
            for p in punches:
                emp = emps.get(p.employe_id)
                rate = float(emp.hourly_rate) if (emp and emp.hourly_rate) else 0.0
                key = (p.employe_id, rate)
                buckets[key] = buckets.get(key, 0.0) + float(p.hours or 0)

            for (emp_id, rate), hours in buckets.items():
                emp = emps.get(emp_id)
                label = emp.full_name if emp else f"Employé #{emp_id}"
                amount = round(hours * rate, 2)
                db.add(
                    FactureItem(
                        facture_id=facture.id,
                        position=pos,
                        description=f"Main-d'œuvre — {label}",
                        unit="h",
                        quantity=round(hours, 2),
                        unit_price=rate,
                        total=amount,
                    )
                )
                pos += 1

    # 3) Matériel — Achats liés à ce projet (chaque achat devient une
    #    ligne quantité 1 au montant de l'achat).
    if data.include_achats:
        achats = (
            await db.execute(
                select(Achat)
                .where(Achat.project_id == project_id)
                .order_by(Achat.id.asc())
            )
        ).scalars().all()
        for ac in achats:
            amount = float(ac.amount or 0)
            desc = ac.description or f"Achat {ac.reference}"
            db.add(
                FactureItem(
                    facture_id=facture.id,
                    position=pos,
                    description=f"Matériel — {desc}",
                    unit="lot",
                    quantity=1,
                    unit_price=amount,
                    total=amount,
                )
            )
            pos += 1

    await db.flush()
    await db.refresh(facture)
    return FactureRead.model_validate(facture)
