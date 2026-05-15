"""Append line items to an existing Facture from the linked project's
soumission, punches and/or achats. Used when an invoice already
exists and the admin wants to pull in additional sources (progress
billing, extras, materials) without recreating it from scratch.
"""

from datetime import datetime, timezone
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
    # Phase A — refacturation des achats avec markup et traçabilité.
    # Si fourni, restreint les achats importés à cette liste. Sinon,
    # tous les achats refacturables (`is_billable=True`) non encore
    # facturés du projet sont importés.
    achat_ids: Optional[list[int]] = Field(default=None)
    # Surcharges de markup par achat : { achat_id: markup_percent }.
    # Si absent, utilise `Achat.markup_percent` (ou 0 si null).
    achat_markup_overrides: dict[int, float] = Field(default_factory=dict)


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

    # 3) Achats — refacturation avec markup et flag anti-doublon.
    #    On ne tire QUE les achats marqués refacturables et qui n'ont
    #    pas encore été versés sur une facture (invoiced_at IS NULL).
    if data.include_achats and fa.project_id:
        stmt = (
            select(Achat)
            .where(Achat.project_id == fa.project_id)
            .where(Achat.is_billable.is_(True))
            .where(Achat.invoiced_at.is_(None))
            .order_by(Achat.id.asc())
        )
        if data.achat_ids:
            stmt = stmt.where(Achat.id.in_(data.achat_ids))
        achats = (await db.execute(stmt)).scalars().all()

        new_items: list[tuple[Achat, FactureItem]] = []
        for ac in achats:
            cost = float(ac.amount or 0)
            markup_pct = float(
                data.achat_markup_overrides.get(ac.id, ac.markup_percent or 0)
            )
            billed = round(cost * (1 + markup_pct / 100.0), 2)
            desc = ac.description or f"Achat {ac.reference or ac.id}"
            if markup_pct > 0:
                # Trace interne du markup dans la description — invisible
                # au client si l'admin réécrit la ligne avant l'envoi.
                desc = f"{desc} (+{markup_pct:g} %)"
            item = FactureItem(
                facture_id=fa.id,
                position=pos,
                description=f"Matériel — {desc}",
                unit="lot",
                quantity=1,
                unit_price=billed,
                total=billed,
            )
            db.add(item)
            new_items.append((ac, item))
            pos += 1
            added += 1

        # Flush pour récupérer les IDs des FactureItem, puis verrouiller
        # les achats avec la date de facturation et le lien retour.
        await db.flush()
        now = datetime.now(timezone.utc)
        for ac, item in new_items:
            ac.invoiced_at = now
            ac.facture_item_id = item.id

    await db.flush()
    return ImportResult(added=added)
