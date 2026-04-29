"""Endpoints internes pour la Promesse d'achat (PA).

Routes :
    POST   /prospection/{lead_id}/purchase-agreements      — créer (auto-prefill)
    GET    /prospection/{lead_id}/purchase-agreements      — lister par lead
    GET    /purchase-agreements/{pa_id}                    — lire détail
    PATCH  /purchase-agreements/{pa_id}                    — modifier champs
    DELETE /purchase-agreements/{pa_id}                    — supprimer
    GET    /purchase-agreements/{pa_id}/pdf                — preview PDF
    POST   /purchase-agreements/{pa_id}/send-to-buyer      — étape 1
    POST   /purchase-agreements/{pa_id}/send-to-seller     — étape 2

Étape 1 : link de signature envoyé à l'acheteur interne (lien
public_base/promesse-achat/acheteur/{token}). Étape 2 : link tokenisé
au vendeur, autorisée seulement après signature acheteur.
"""

from __future__ import annotations

from datetime import date as DateT, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.prospection_lead import ProspectionLead
from app.models.purchase_agreement import (
    PurchaseAgreement,
    PurchaseAgreementStatus,
)
from app.models.purchase_agreement_template import PurchaseAgreementTemplate
from app.services.purchase_agreement_pdf import render_purchase_agreement_pdf
from app.services.purchase_agreement_send import (
    PurchaseAgreementSendError,
    send_to_buyer,
    send_to_seller,
)


router = APIRouter(tags=["purchase-agreements"])


# --------------------------- Schemas ---------------------------


class PurchaseAgreementBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    buyer_1_name: Optional[str] = None
    buyer_1_address: Optional[str] = None
    buyer_1_phone_day: Optional[str] = None
    buyer_1_phone_eve: Optional[str] = None
    buyer_1_email: Optional[str] = None
    buyer_2_name: Optional[str] = None
    buyer_2_address: Optional[str] = None
    buyer_2_phone_day: Optional[str] = None
    buyer_2_phone_eve: Optional[str] = None
    buyer_2_email: Optional[str] = None
    seller_1_name: Optional[str] = None
    seller_1_address: Optional[str] = None
    seller_1_phone_day: Optional[str] = None
    seller_1_phone_eve: Optional[str] = None
    seller_1_email: Optional[str] = None
    seller_2_name: Optional[str] = None
    seller_2_address: Optional[str] = None
    seller_2_phone_day: Optional[str] = None
    seller_2_phone_eve: Optional[str] = None
    seller_2_email: Optional[str] = None

    property_address: Optional[str] = None
    lot_designation: Optional[str] = None
    lot_width: Optional[float] = None
    lot_depth: Optional[float] = None
    lot_dimension_unit: Optional[str] = None
    lot_area: Optional[float] = None
    lot_area_unit: Optional[str] = None

    price: Optional[float] = None
    down_payment: Optional[float] = None
    mortgage_amount: Optional[float] = None
    deposit_amount: Optional[float] = None
    deposit_notary: Optional[str] = None

    visit_date: Optional[DateT] = None
    rented_appliances_text: Optional[str] = None

    annual_rents: Optional[float] = None
    leases_expiry_text: Optional[str] = None

    financing_kind: Optional[str] = None
    financing_min_pct: Optional[float] = None
    financing_max_rate: Optional[float] = None
    financing_amortization_years: Optional[int] = None
    financing_min_term_years: Optional[int] = None
    inspection_enabled: Optional[bool] = None
    inspection_days: Optional[int] = None
    visit_units_enabled: Optional[bool] = None
    water_septic_enabled: Optional[bool] = None
    buyer_property_sale_enabled: Optional[bool] = None
    buyer_property_address: Optional[str] = None
    buyer_property_deadline: Optional[DateT] = None
    conditional_other_offer_enabled: Optional[bool] = None
    other_offer_date: Optional[DateT] = None

    act_of_sale_date: Optional[DateT] = None
    occupation_date: Optional[DateT] = None
    occupation_time: Optional[str] = None
    occupation_compensation_per_month: Optional[float] = None
    baux_text: Optional[str] = None
    inclusions_text: Optional[str] = None
    exclusions_text: Optional[str] = None

    other_conditions_text: Optional[str] = None

    acceptance_deadline_date: Optional[DateT] = None
    acceptance_deadline_time: Optional[str] = None

    notes: Optional[str] = None


class PurchaseAgreementCreate(PurchaseAgreementBase):
    pass


class PurchaseAgreementUpdate(PurchaseAgreementBase):
    pass


class PurchaseAgreementRead(PurchaseAgreementBase):
    id: int
    reference: str
    lead_id: int
    status: str
    created_by_user_id: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]
    sent_to_seller_at: Optional[datetime]
    buyer_signed_at: Optional[datetime]
    buyer_signed_name: Optional[str]
    seller_signed_at: Optional[datetime]
    seller_signed_name: Optional[str]
    seller_response: Optional[str]
    seller_rejection_reason: Optional[str]


class SendBuyerRequest(BaseModel):
    to: List[EmailStr] = Field(..., min_length=1, max_length=5)
    cc: Optional[List[EmailStr]] = None
    subject: Optional[str] = Field(default=None, max_length=255)
    message: Optional[str] = Field(default=None, max_length=4000)


class SendSellerRequest(BaseModel):
    to: List[EmailStr] = Field(..., min_length=1, max_length=5)
    cc: Optional[List[EmailStr]] = None
    subject: Optional[str] = Field(default=None, max_length=255)
    message: Optional[str] = Field(default=None, max_length=4000)


# --------------------------- Helpers ---------------------------


def _next_reference(last_id: int) -> str:
    return f"PA-{last_id + 1:05d}"


async def _load_pa_or_404(db, pa_id: int) -> PurchaseAgreement:
    pa = (
        await db.execute(
            select(PurchaseAgreement).where(PurchaseAgreement.id == pa_id)
        )
    ).scalar_one_or_none()
    if pa is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Promesse d'achat introuvable."
        )
    return pa


async def _load_lead_or_404(db, lead_id: int) -> ProspectionLead:
    lead = (
        await db.execute(
            select(ProspectionLead).where(ProspectionLead.id == lead_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead introuvable.")
    return lead


def _apply_partial(pa: PurchaseAgreement, data: PurchaseAgreementBase) -> None:
    payload = data.model_dump(exclude_unset=True)
    for key, value in payload.items():
        setattr(pa, key, value)


# --------------------------- Endpoints ---------------------------


@router.post(
    "/prospection/{lead_id}/purchase-agreements",
    response_model=PurchaseAgreementRead,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une promesse d'achat pour un lead",
)
async def create_purchase_agreement(
    lead_id: int,
    payload: PurchaseAgreementCreate,
    db: DBSession,
    user: CurrentUser,
) -> PurchaseAgreementRead:
    lead = await _load_lead_or_404(db, lead_id)
    last_id = (
        await db.execute(
            select(PurchaseAgreement.id)
            .order_by(PurchaseAgreement.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or 0

    # Charge le template singleton de defaults (s'il existe)
    tpl = (
        await db.execute(select(PurchaseAgreementTemplate).limit(1))
    ).scalar_one_or_none()

    pa = PurchaseAgreement(
        reference=_next_reference(last_id),
        lead_id=lead.id,
        created_by_user_id=user.id,
        status=PurchaseAgreementStatus.DRAFT.value,
        # Pré-remplissage depuis le lead (priorité 1)
        property_address=lead.address,
        seller_1_name=lead.owner_name,
        seller_1_address=lead.owner_address or lead.mailing_address,
        seller_1_phone_day=lead.owner_phone,
        seller_1_email=lead.owner_email,
        # Acheteur — depuis template si défini, sinon utilisateur courant
        buyer_1_name=(tpl.default_buyer_1_name if tpl and tpl.default_buyer_1_name
                      else user.email),
        buyer_1_address=tpl.default_buyer_1_address if tpl else None,
        buyer_1_email=(tpl.default_buyer_1_email if tpl and tpl.default_buyer_1_email
                       else user.email),
        buyer_1_phone_day=tpl.default_buyer_1_phone_day if tpl else None,
        # Defaults financement / conditions / clauses
        financing_kind=tpl.financing_kind if tpl else "hypothecaire",
        financing_min_pct=tpl.financing_min_pct if tpl else None,
        financing_max_rate=tpl.financing_max_rate if tpl else None,
        financing_amortization_years=(
            tpl.financing_amortization_years if tpl else None
        ),
        financing_min_term_years=tpl.financing_min_term_years if tpl else None,
        inspection_enabled=tpl.inspection_enabled if tpl else True,
        inspection_days=tpl.inspection_days if tpl else 10,
        visit_units_enabled=tpl.visit_units_enabled if tpl else False,
        water_septic_enabled=tpl.water_septic_enabled if tpl else False,
        baux_text=tpl.baux_text if tpl else None,
        inclusions_text=tpl.inclusions_text if tpl else None,
        exclusions_text=tpl.exclusions_text if tpl else None,
        other_conditions_text=tpl.other_conditions_text if tpl else None,
    )
    _apply_partial(pa, payload)
    db.add(pa)
    await db.flush()
    await db.refresh(pa)
    return PurchaseAgreementRead.model_validate(pa)


@router.get(
    "/prospection/{lead_id}/purchase-agreements",
    response_model=List[PurchaseAgreementRead],
    summary="Lister les PA d'un lead",
)
async def list_purchase_agreements(
    lead_id: int, db: DBSession, _: CurrentUser
) -> List[PurchaseAgreementRead]:
    await _load_lead_or_404(db, lead_id)
    rows = (
        await db.execute(
            select(PurchaseAgreement)
            .where(PurchaseAgreement.lead_id == lead_id)
            .order_by(PurchaseAgreement.id.desc())
        )
    ).scalars().all()
    return [PurchaseAgreementRead.model_validate(r) for r in rows]


@router.get(
    "/purchase-agreements/{pa_id}",
    response_model=PurchaseAgreementRead,
    summary="Lire le détail d'une PA",
)
async def get_purchase_agreement(
    pa_id: int, db: DBSession, _: CurrentUser
) -> PurchaseAgreementRead:
    pa = await _load_pa_or_404(db, pa_id)
    return PurchaseAgreementRead.model_validate(pa)


@router.patch(
    "/purchase-agreements/{pa_id}",
    response_model=PurchaseAgreementRead,
    summary="Modifier une PA",
)
async def update_purchase_agreement(
    pa_id: int,
    payload: PurchaseAgreementUpdate,
    db: DBSession,
    _: CurrentUser,
) -> PurchaseAgreementRead:
    pa = await _load_pa_or_404(db, pa_id)
    if pa.status not in (
        PurchaseAgreementStatus.DRAFT.value,
        PurchaseAgreementStatus.PENDING_BUYER_SIGNATURE.value,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "PA déjà envoyée au vendeur — non modifiable.",
        )
    _apply_partial(pa, payload)
    await db.flush()
    await db.refresh(pa)
    return PurchaseAgreementRead.model_validate(pa)


@router.delete(
    "/purchase-agreements/{pa_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une PA",
)
async def delete_purchase_agreement(
    pa_id: int, db: DBSession, _: CurrentUser
) -> Response:
    pa = await _load_pa_or_404(db, pa_id)
    if pa.status == PurchaseAgreementStatus.ACCEPTED.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "PA acceptée — impossible de supprimer.",
        )
    await db.delete(pa)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/purchase-agreements/{pa_id}/pdf",
    summary="Aperçu PDF (interne)",
)
async def get_purchase_agreement_pdf(
    pa_id: int, db: DBSession, _: CurrentUser
) -> Response:
    pa = await _load_pa_or_404(db, pa_id)
    pdf_bytes = await render_purchase_agreement_pdf(db, pa.id)
    filename = f"promesse-achat-{pa.reference}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post(
    "/purchase-agreements/{pa_id}/send-to-buyer",
    response_model=PurchaseAgreementRead,
    summary="Étape 1 — envoyer la PA à l'acheteur interne pour signature",
)
async def send_purchase_agreement_to_buyer(
    pa_id: int,
    payload: SendBuyerRequest,
    db: DBSession,
    _: CurrentUser,
) -> PurchaseAgreementRead:
    pa = await _load_pa_or_404(db, pa_id)
    if pa.status not in (
        PurchaseAgreementStatus.DRAFT.value,
        PurchaseAgreementStatus.PENDING_BUYER_SIGNATURE.value,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "PA déjà signée par l'acheteur — utiliser /send-to-seller.",
        )
    try:
        await send_to_buyer(
            db,
            pa_id,
            to=[str(e) for e in payload.to],
            cc=[str(e) for e in (payload.cc or [])],
            subject=payload.subject,
            message=payload.message,
        )
    except PurchaseAgreementSendError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    await db.refresh(pa)
    return PurchaseAgreementRead.model_validate(pa)


@router.post(
    "/purchase-agreements/{pa_id}/send-to-seller",
    response_model=PurchaseAgreementRead,
    summary="Étape 2 — envoyer la PA signée au vendeur pour réponse",
)
async def send_purchase_agreement_to_seller(
    pa_id: int,
    payload: SendSellerRequest,
    db: DBSession,
    _: CurrentUser,
) -> PurchaseAgreementRead:
    pa = await _load_pa_or_404(db, pa_id)
    if pa.status != PurchaseAgreementStatus.PENDING_SELLER_SIGNATURE.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "L'acheteur doit signer avant l'envoi au vendeur.",
        )
    try:
        await send_to_seller(
            db,
            pa_id,
            to=[str(e) for e in payload.to],
            cc=[str(e) for e in (payload.cc or [])],
            subject=payload.subject,
            message=payload.message,
        )
    except PurchaseAgreementSendError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    await db.refresh(pa)
    return PurchaseAgreementRead.model_validate(pa)
