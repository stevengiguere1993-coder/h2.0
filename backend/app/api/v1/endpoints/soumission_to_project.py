"""Convert an accepted soumission into a Project.

Creates a new Project linked back to the Soumission + ContactRequest,
pre-filling name / address / budget from the soumission context.
Idempotent when a project already exists for that soumission: the
existing one is returned unchanged.

When a project is freshly created (not on the idempotent path), a
25 % deposit Facture is automatically created in DRAFT status with
Quebec taxes (TPS 5 %, TVQ 9.975 %). The percentage and due date
can be tuned via the optional request body. Pass ``deposit_percentage
= 0`` to skip the deposit invoice entirely.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.contact_request import ContactRequest
from app.models.facture import Facture, FactureStatus
from app.models.facture_item import FactureItem
from app.models.project import Project, ProjectStatus
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem
from app.schemas.project import ProjectRead


router = APIRouter(prefix="/soumissions", tags=["soumission-to-project"])

TPS_RATE = 0.05
TVQ_RATE = 0.09975


class ConvertToProjectRequest(BaseModel):
    deposit_percentage: int = Field(
        default=25, ge=0, le=100,
        description=(
            "Pourcentage de la soumission à facturer en acompte. "
            "Met à 0 pour ne pas créer de facture d'acompte."
        ),
    )
    due_in_days: int = Field(
        default=0, ge=0, le=365,
        description=(
            "Délai de paiement de l'acompte (jours). 0 = payable sur "
            "réception (défaut pour un dépôt)."
        ),
    )


def _build_facture_ref() -> str:
    d = datetime.now(timezone.utc)
    return (
        f"FAC-{d.year}{d.month:02d}{d.day:02d}-"
        f"{d.hour:02d}{d.minute:02d}{d.second:02d}"
    )


async def _soumission_subtotal(db, sm: Soumission) -> float:
    """Return the soumission subtotal — prefer the stored value, fall
    back to summing line items when the column is null (older records
    or freshly imported soumissions)."""
    if sm.subtotal is not None and float(sm.subtotal) > 0:
        return float(sm.subtotal)
    rows = (
        await db.execute(
            select(SoumissionItem.quantity, SoumissionItem.unit_price,
                   SoumissionItem.total)
            .where(SoumissionItem.soumission_id == sm.id)
        )
    ).all()
    total = 0.0
    for qty, unit_price, line_total in rows:
        if line_total is not None and float(line_total) > 0:
            total += float(line_total)
        else:
            total += float(qty or 0) * float(unit_price or 0)
    return round(total, 2)


@router.post(
    "/{soumission_id}/convert-to-project",
    response_model=ProjectRead,
    summary="Create or fetch a project from a soumission (auto deposit invoice)",
)
async def convert_soumission_to_project(
    soumission_id: int,
    db: DBSession,
    _: CurrentUser,
    body: Optional[ConvertToProjectRequest] = None,
) -> ProjectRead:
    sm = (
        await db.execute(select(Soumission).where(Soumission.id == soumission_id))
    ).scalar_one_or_none()
    if sm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Soumission not found")

    # Idempotent: if a project already points at this soumission, return it.
    existing = (
        await db.execute(
            select(Project).where(Project.soumission_id == soumission_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return ProjectRead.model_validate(existing)

    # Pull contact info (address / name) from the linked prospect.
    contact: ContactRequest | None = None
    if sm.contact_request_id:
        contact = (
            await db.execute(
                select(ContactRequest).where(
                    ContactRequest.id == sm.contact_request_id
                )
            )
        ).scalar_one_or_none()

    project = Project(
        name=sm.title or f"Projet {sm.reference}",
        contact_request_id=sm.contact_request_id,
        soumission_id=sm.id,
        client_id=sm.client_id,
        status=ProjectStatus.PLANNED.value,
        address=(contact.address if contact else None),
        description=sm.description,
        budget=sm.total,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)

    # ---------- Acompte automatique ----------
    cfg = body or ConvertToProjectRequest()
    pct = cfg.deposit_percentage
    if pct > 0:
        sm_subtotal = await _soumission_subtotal(db, sm)
        if sm_subtotal > 0:
            ratio = pct / 100.0
            deposit_subtotal = round(sm_subtotal * ratio, 2)
            tps = round(deposit_subtotal * TPS_RATE, 2)
            tvq = round(deposit_subtotal * TVQ_RATE, 2)
            grand_total = round(deposit_subtotal + tps + tvq, 2)

            facture = Facture(
                reference=_build_facture_ref(),
                client_id=project.client_id,
                project_id=project.id,
                status=FactureStatus.DRAFT.value,
                issued_at=datetime.now(timezone.utc),
                due_at=(
                    datetime.now(timezone.utc)
                    + timedelta(days=cfg.due_in_days)
                ),
                subtotal=deposit_subtotal,
                tps=tps,
                tvq=tvq,
                total=grand_total,
                balance=grand_total,
                client_note=(
                    f"Acompte de {pct} % sur la soumission {sm.reference}. "
                    "Le solde sera facturé selon l'avancement des travaux."
                ),
            )
            db.add(facture)
            await db.flush()
            db.add(
                FactureItem(
                    facture_id=facture.id,
                    position=0,
                    description=(
                        f"Acompte {pct} % — Soumission {sm.reference}"
                        + (f" — {sm.title}" if sm.title else "")
                    ),
                    unit="lot",
                    quantity=1,
                    unit_price=deposit_subtotal,
                    total=deposit_subtotal,
                )
            )
            await db.flush()

    return ProjectRead.model_validate(project)
