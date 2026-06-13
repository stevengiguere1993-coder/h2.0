"""Send a bon de travail to a client + PDF preview."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, DBSession
from app.schemas.business import BonTravailRead
from app.services.bon_pdf import render_bon_pdf
from app.services.bon_send import BonSendError, send_bon


router = APIRouter(prefix="/bons-travail", tags=["bon-send"])


class BonSendRequest(BaseModel):
    to: List[EmailStr] = Field(..., min_length=1)
    cc: Optional[List[EmailStr]] = None
    subject: Optional[str] = Field(default=None, max_length=255)
    message: Optional[str] = Field(default=None, max_length=4000)


@router.post(
    "/{bon_id}/send",
    response_model=BonTravailRead,
    summary="Send a bon to a client (PDF + signature link)",
)
async def send_bon_endpoint(
    bon_id: int,
    data: BonSendRequest,
    db: DBSession,
    _: CurrentUser,
) -> BonTravailRead:
    try:
        bon = await send_bon(
            db,
            bon_id,
            to=[str(a) for a in data.to],
            cc=[str(a) for a in (data.cc or [])],
            subject=data.subject,
            message=data.message,
        )
    except BonSendError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return BonTravailRead.model_validate(bon)


@router.get("/{bon_id}/pdf", summary="Inline PDF preview")
async def get_bon_pdf(
    bon_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    rendered = await render_bon_pdf(db, bon_id)
    if rendered is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bon not found")
    bon, pdf_bytes = rendered
    filename = f"bon-{bon.reference}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/{bon_id}/ensure-project")
async def ensure_bon_project(
    bon_id: int, db: DBSession, user: CurrentUser
) -> dict:
    """Garantit qu'un bon de travail a un PROJET lié (kind=bon_travail)
    pour porter ses achats / heures / facture. Idempotent : renvoie le
    projet existant si déjà lié, sinon en crée un (titre/client/assigné
    repris du bon)."""
    from app.models.bon_travail import BonTravail
    from app.models.project import Project, ProjectStatus

    bon = await db.get(BonTravail, bon_id)
    if bon is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bon introuvable.")
    if bon.project_id:
        return {"project_id": bon.project_id}
    proj = Project(
        name=bon.title or f"Bon {bon.reference}",
        client_id=bon.client_id,
        kind="bon_travail",
        responsible_user_id=getattr(bon, "assignee_user_id", None),
        status=ProjectStatus.IN_PROGRESS.value,
    )
    db.add(proj)
    await db.flush()
    bon.project_id = proj.id
    await db.flush()
    return {"project_id": proj.id}


@router.get("/{bon_id}/recap")
async def bon_recap(bon_id: int, db: DBSession, user: CurrentUser) -> dict:
    """Récap du montant chargé au client pour un bon de travail.

    - garantie       → 0 $ (travaux sous garantie).
    - temps_materiel → heures punchées (× taux facturable) + achats
      refacturables (coût + markup / contrat) du PROJET lié. Lecture
      seule : ne marque rien comme facturé."""
    from sqlalchemy import select

    from app.api.v1.endpoints.facture_import import _compute_billed_amount
    from app.models.achat import Achat
    from app.models.bon_travail import BonTravail
    from app.models.employe import Employe
    from app.models.project_subcontractor_contract import (
        ProjectSubcontractorContract,
    )
    from app.models.punch import Punch

    bon = await db.get(BonTravail, bon_id)
    if bon is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bon introuvable.")

    fixed_amount = float(bon.amount) if bon.amount is not None else None
    out = {
        "bon_type": bon.bon_type,
        "hours": 0.0,
        "labor_total": 0.0,
        "achats_total": 0.0,
        "fixed_amount": fixed_amount,
        "total": 0.0,
    }
    if bon.bon_type == "garantie":
        return out

    pid = bon.project_id
    if not pid:
        # Pas encore de projet lié : si un montant fixe est saisi on
        # l'utilise, sinon 0 (rien d'ajouté).
        out["total"] = round(fixed_amount or 0.0, 2)
        return out

    # Heures (T&M)
    punches = (
        await db.execute(
            select(Punch).where(
                Punch.project_id == pid, Punch.hours.is_not(None)
            )
        )
    ).scalars().all()
    emp_ids = {p.employe_id for p in punches}
    emps = {}
    if emp_ids:
        emps = {
            e.id: e
            for e in (
                await db.execute(
                    select(Employe).where(Employe.id.in_(emp_ids))
                )
            ).scalars().all()
        }
    hours = 0.0
    labor = 0.0
    for p in punches:
        emp = emps.get(p.employe_id)
        if emp and emp.billing_rate is not None:
            rate = float(emp.billing_rate)
        elif emp and emp.hourly_rate:
            rate = float(emp.hourly_rate)
        else:
            rate = 0.0
        h = float(p.hours or 0)
        hours += h
        labor += h * rate

    # Achats refacturables
    achats = (
        await db.execute(
            select(Achat).where(
                Achat.project_id == pid, Achat.is_billable.is_(True)
            )
        )
    ).scalars().all()
    sub_ids = {a.sous_traitant_id for a in achats if a.sous_traitant_id}
    contracts_by_st = {}
    if sub_ids:
        rows = (
            await db.execute(
                select(ProjectSubcontractorContract).where(
                    ProjectSubcontractorContract.project_id == pid,
                    ProjectSubcontractorContract.sous_traitant_id.in_(sub_ids),
                )
            )
        ).scalars().all()
        contracts_by_st = {c.sous_traitant_id: c for c in rows}
    achats_total = 0.0
    for ac in achats:
        billed, _ = _compute_billed_amount(ac, {}, contracts_by_st)
        achats_total += billed

    out["hours"] = round(hours, 2)
    out["labor_total"] = round(labor, 2)
    out["achats_total"] = round(achats_total, 2)
    out["total"] = round(labor + achats_total, 2)
    return out
