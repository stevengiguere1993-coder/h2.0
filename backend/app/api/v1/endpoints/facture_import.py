"""Append line items to an existing Facture from the linked project's
soumission, punches and/or achats. Used when an invoice already
exists and the admin wants to pull in additional sources (progress
billing, extras, materials) without recreating it from scratch.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.achat import Achat
from app.models.employe import Employe
from app.models.facture import Facture
from app.models.facture_item import FactureItem
from app.models.punch import Punch
from app.models.soumission import Soumission, SoumissionStatus
from app.models.soumission_item import SoumissionItem


router = APIRouter(prefix="/factures", tags=["facture-import"])


class ImportRequest(BaseModel):
    include_soumission: bool = False
    soumission_percentage: int = Field(default=100, ge=1, le=100)
    soumission_id: Optional[int] = Field(
        default=None,
        description=(
            "Specific soumission to import items from. Defaults to the "
            "project's linked soumission when omitted."
        ),
    )
    include_hours: bool = False
    only_approved: bool = True
    include_achats: bool = False


class ImportResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    added: int


@router.post(
    "/{facture_id}/import-sources",
    response_model=ImportResult,
    summary="Append items to an existing facture from project sources",
)
async def import_into_facture(
    facture_id: int,
    data: ImportRequest,
    db: DBSession,
    _: CurrentUser,
) -> ImportResult:
    fa = (
        await db.execute(select(Facture).where(Facture.id == facture_id))
    ).scalar_one_or_none()
    if fa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Facture not found")

    # Next position = max existing position + 1
    existing = (
        await db.execute(
            select(FactureItem.position).where(FactureItem.facture_id == facture_id)
        )
    ).scalars().all()
    pos = (max(existing) + 1) if existing else 0

    added = 0

    # 1) Soumission items
    if data.include_soumission:
        soumission_id = data.soumission_id
        if not soumission_id and fa.project_id:
            # Pull the soumission_id from the linked project if any.
            from app.models.project import Project as _Project
            project = (
                await db.execute(
                    select(_Project).where(_Project.id == fa.project_id)
                )
            ).scalar_one_or_none()
            if project and project.soumission_id:
                soumission_id = project.soumission_id

        if soumission_id:
            sm = (
                await db.execute(
                    select(Soumission).where(Soumission.id == soumission_id)
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
                            facture_id=fa.id,
                            position=pos,
                            description=f"{prefix}{it.description}",
                            unit=it.unit,
                            quantity=qty,
                            unit_price=unit_price,
                            total=line_total,
                        )
                    )
                    pos += 1
                    added += 1

    # 2) Punched hours
    if data.include_hours and fa.project_id:
        stmt = select(Punch).where(Punch.project_id == fa.project_id)
        if data.only_approved:
            stmt = stmt.where(Punch.approved.is_(True))
        stmt = stmt.where(Punch.hours.is_not(None))
        punches = (await db.execute(stmt)).scalars().all()
        if punches:
            emp_ids = {p.employe_id for p in punches}
            emps = {
                e.id: e
                for e in (
                    await db.execute(select(Employe).where(Employe.id.in_(emp_ids)))
                ).scalars().all()
            }
            buckets: dict[tuple[int, float], float] = {}
            for p in punches:
                emp = emps.get(p.employe_id)
                rate = float(emp.hourly_rate) if (emp and emp.hourly_rate) else 0.0
                buckets[(p.employe_id, rate)] = (
                    buckets.get((p.employe_id, rate), 0.0) + float(p.hours or 0)
                )
            for (emp_id, rate), hours in buckets.items():
                emp = emps.get(emp_id)
                label = emp.full_name if emp else f"Employé #{emp_id}"
                db.add(
                    FactureItem(
                        facture_id=fa.id,
                        position=pos,
                        description=f"Main-d'œuvre — {label}",
                        unit="h",
                        quantity=round(hours, 2),
                        unit_price=rate,
                        total=round(hours * rate, 2),
                    )
                )
                pos += 1
                added += 1

    # 3) Achats
    if data.include_achats and fa.project_id:
        achats = (
            await db.execute(
                select(Achat)
                .where(Achat.project_id == fa.project_id)
                .order_by(Achat.id.asc())
            )
        ).scalars().all()
        for ac in achats:
            amount = float(ac.amount or 0)
            desc = ac.description or f"Achat {ac.reference}"
            db.add(
                FactureItem(
                    facture_id=fa.id,
                    position=pos,
                    description=f"Matériel — {desc}",
                    unit="lot",
                    quantity=1,
                    unit_price=amount,
                    total=amount,
                )
            )
            pos += 1
            added += 1

    await db.flush()
    return ImportResult(added=added)
