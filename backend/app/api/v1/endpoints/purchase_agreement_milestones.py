"""Échéances clés des promesses d'achat (visite, inspection, occupation,
acte notarié, délai de réponse) — agrégées on-the-fly depuis les PA
actives pour alimenter le widget « Prochains jours » et l'agenda.

Routes :
    GET /prospection/pa-milestones?days=7        — toutes les PA actives
    GET /prospection/{lead_id}/pa-milestones     — pour un lead précis
"""

from __future__ import annotations

from datetime import date as DateT, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.prospection_lead import ProspectionLead
from app.models.purchase_agreement import (
    PurchaseAgreement,
    PurchaseAgreementStatus,
)


router = APIRouter(prefix="/prospection", tags=["pa-milestones"])


class Milestone(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pa_id: int
    pa_reference: str
    lead_id: int
    lead_name: Optional[str]
    property_address: Optional[str]
    kind: str  # "visite" | "inspection" | "acceptance" | "occupation" | "acte"
    label: str
    when: DateT
    status: str


_LIVE_STATUSES = (
    PurchaseAgreementStatus.DRAFT.value,
    PurchaseAgreementStatus.PENDING_BUYER_SIGNATURE.value,
    PurchaseAgreementStatus.PENDING_SELLER_SIGNATURE.value,
    PurchaseAgreementStatus.ACCEPTED.value,
)


def _milestones_for_pa(
    pa: PurchaseAgreement, lead: Optional[ProspectionLead]
) -> List[Milestone]:
    out: List[Milestone] = []
    lead_name = lead.name if lead else None
    addr = pa.property_address or (lead.address if lead else None)

    def add(kind: str, label: str, when: Optional[DateT]) -> None:
        if when is None:
            return
        out.append(
            Milestone(
                pa_id=pa.id,
                pa_reference=pa.reference,
                lead_id=pa.lead_id,
                lead_name=lead_name,
                property_address=addr,
                kind=kind,
                label=label,
                when=when,
                status=pa.status,
            )
        )

    # Visite (capturée dans la PA)
    add("visite", "Visite de l'immeuble", pa.visit_date)

    # Inspection — pa.inspection_days après acceptation, fallback sur
    # création si pas encore signée.
    if pa.inspection_enabled:
        anchor: Optional[datetime] = pa.seller_signed_at or pa.created_at
        if anchor is not None:
            inspection_deadline = (anchor + timedelta(days=pa.inspection_days)).date()
            add(
                "inspection",
                f"Fin du délai d'inspection ({pa.inspection_days} j)",
                inspection_deadline,
            )

    # Délai d'acceptation
    add(
        "acceptance", "Délai d'acceptation par le vendeur",
        pa.acceptance_deadline_date,
    )

    # Occupation
    add("occupation", "Occupation par l'acheteur", pa.occupation_date)

    # Acte notarié
    add("acte", "Signature de l'acte de vente", pa.act_of_sale_date)

    return out


@router.get(
    "/pa-milestones",
    response_model=List[Milestone],
    summary="Échéances PA dans les N prochains jours (toutes PA actives)",
)
async def list_milestones(
    db: DBSession,
    _: CurrentUser,
    days: int = Query(default=7, ge=1, le=365),
) -> List[Milestone]:
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=days)

    pas = (
        await db.execute(
            select(PurchaseAgreement).where(
                PurchaseAgreement.status.in_(_LIVE_STATUSES)
            )
        )
    ).scalars().all()

    if not pas:
        return []

    lead_ids = list({pa.lead_id for pa in pas})
    leads_rows = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id.in_(lead_ids))
        )
    ).scalars().all()
    leads_by_id = {l.id: l for l in leads_rows}

    out: List[Milestone] = []
    for pa in pas:
        lead = leads_by_id.get(pa.lead_id)
        out.extend(_milestones_for_pa(pa, lead))

    out = [m for m in out if today <= m.when <= horizon]
    out.sort(key=lambda m: (m.when, m.pa_id))
    return out


@router.get(
    "/{lead_id}/pa-milestones",
    response_model=List[Milestone],
    summary="Échéances PA pour un lead précis",
)
async def list_milestones_for_lead(
    lead_id: int,
    db: DBSession,
    _: CurrentUser,
) -> List[Milestone]:
    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        return []

    pas = (
        await db.execute(
            select(PurchaseAgreement).where(
                PurchaseAgreement.lead_id == lead_id
            )
        )
    ).scalars().all()

    out: List[Milestone] = []
    for pa in pas:
        out.extend(_milestones_for_pa(pa, lead))
    out.sort(key=lambda m: (m.when, m.pa_id))
    return out
