"""Settings UI pour la numérotation séquentielle des factures et
soumissions. Permet à l'admin d'aligner les compteurs avec une suite
QuickBooks existante (ex. dernière facture QB = 96 → prochain = 97).

    GET    /api/v1/settings/numbering
    PATCH  /api/v1/settings/numbering
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentAdmin, DBSession
from app.models.numbering_counter import NumberingCounter
from app.services.numbering import _ensure_row, aligner_compteur_factures


router = APIRouter(prefix="/settings/numbering", tags=["numbering"])


class NumberingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    next_facture_number: int
    next_soumission_number: int
    next_po_number: int


class NumberingUpdate(BaseModel):
    next_facture_number: Optional[int] = Field(default=None, ge=1, le=999_999_999)
    next_soumission_number: Optional[int] = Field(default=None, ge=1, le=999_999_999)
    next_po_number: Optional[int] = Field(default=None, ge=1, le=999_999_999)


class AlignementFactures(BaseModel):
    """Résultat du recalage du compteur de factures sur Kratos + QB."""

    avant: int
    apres: int
    kratos_max: int
    #: Plus haut numéro dans QuickBooks ; None si QB n'a pas répondu.
    qb_max: Optional[int] = None
    qb_consulte: bool
    #: Numéros QuickBooks ignorés : hors de la série de Kratos.
    qb_hors_serie: list[int] = []
    compteurs: NumberingRead


@router.post(
    "/aligner-factures",
    response_model=AlignementFactures,
    summary="Recale le compteur de factures sur le plus haut numéro (Kratos ou QuickBooks) + 1",
)
async def aligner_factures(db: DBSession, _: CurrentAdmin) -> AlignementFactures:
    """Prochain numéro de facture = plus haut numéro existant + 1, entre
    Kratos et QuickBooks. Ne baisse jamais le compteur. Le même recalage
    tourne au démarrage, à chaque attribution de numéro et toutes les
    heures ; ce bouton sert à vérifier ou à forcer tout de suite."""
    res = await aligner_compteur_factures(db)
    await db.commit()
    fresh = (
        await db.execute(
            select(NumberingCounter).where(NumberingCounter.id == 1)
        )
    ).scalar_one()
    return AlignementFactures(
        **res, compteurs=NumberingRead.model_validate(fresh)
    )


class RenumerotationFactures(BaseModel):
    """Remise dans la suite des factures numérotées hors série (10xx)."""

    seuil: int = Field(default=1000, ge=2, le=999_999_999)
    #: Premier numéro à donner ; vide = plus haut numéro sous le seuil + 1.
    premier: Optional[int] = Field(default=None, ge=1, le=999_999_999)
    simuler: bool = True


@router.get(
    "/renumerotation-factures",
    summary="Aperçu : factures hors série (10xx) remises dans la suite, en ordre d'envoi",
)
async def apercu_renumerotation_factures(
    db: DBSession,
    _: CurrentAdmin,
    seuil: int = 1000,
    premier: Optional[int] = None,
) -> dict:
    """Lecture seule : le plan (ancien → nouveau numéro), les numéros
    sautés parce que QuickBooks les a déjà, et les factures QuickBooks
    hors série qui ne viennent pas de Kratos (cause du saut)."""
    from app.services.facture_renumerotation import renumeroter_factures_hors_serie

    return await renumeroter_factures_hors_serie(
        db, seuil=seuil, premier=premier, simuler=True
    )


@router.post(
    "/renumerotation-factures",
    summary="Remet les factures hors série (10xx) dans la suite, Kratos et QuickBooks",
)
async def renumerotation_factures(
    data: RenumerotationFactures, db: DBSession, _: CurrentAdmin
) -> dict:
    """``simuler`` vrai (défaut) : le plan seulement. Faux : chaque facture
    prend son nouveau numéro dans Kratos puis dans QuickBooks (DocNumber),
    dans l'ordre d'envoi, et le compteur repart juste après."""
    from fastapi import HTTPException

    from app.services.facture_renumerotation import renumeroter_factures_hors_serie

    try:
        return await renumeroter_factures_hors_serie(
            db, seuil=data.seuil, premier=data.premier, simuler=data.simuler
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail={"message": str(exc)})


class RenumerotationFactureQb(BaseModel):
    """Numéro de la série de Kratos pour une facture faite à la main dans
    QuickBooks (absente de Kratos)."""

    qbo_invoice_id: str = Field(min_length=1, max_length=32)
    #: Vide = prochain numéro du compteur.
    numero: Optional[str] = Field(default=None, max_length=21)


@router.post(
    "/renumerotation-facture-qb",
    summary="Donne un numéro de la série de Kratos à une facture QuickBooks absente de Kratos",
)
async def renumerotation_facture_qb(
    data: RenumerotationFactureQb, db: DBSession, _: CurrentAdmin
) -> dict:
    from fastapi import HTTPException

    from app.services.facture_renumerotation import renumeroter_facture_qb_seule

    try:
        return await renumeroter_facture_qb_seule(
            db, qbo_invoice_id=data.qbo_invoice_id, numero=data.numero
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc)})
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail={"message": str(exc)})


@router.get("", response_model=NumberingRead)
async def get_numbering(
    db: DBSession, _: CurrentAdmin
) -> NumberingRead:
    row = await _ensure_row(db)
    await db.commit()
    return NumberingRead.model_validate(row)


@router.patch("", response_model=NumberingRead, status_code=status.HTTP_200_OK)
async def update_numbering(
    data: NumberingUpdate, db: DBSession, _: CurrentAdmin
) -> NumberingRead:
    row = await _ensure_row(db)
    if data.next_facture_number is not None:
        row.next_facture_number = data.next_facture_number
    if data.next_soumission_number is not None:
        row.next_soumission_number = data.next_soumission_number
    if data.next_po_number is not None:
        row.next_po_number = data.next_po_number
    await db.flush()
    await db.commit()
    fresh = (
        await db.execute(
            select(NumberingCounter).where(NumberingCounter.id == 1)
        )
    ).scalar_one()
    return NumberingRead.model_validate(fresh)
