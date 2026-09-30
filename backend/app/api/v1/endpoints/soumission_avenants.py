"""Avenants (change orders) d'un devis accepté.

Retour 2026-09-15 : le devis accepté est figé ; tout changement demandé
par le client en cours de route passe par ici.

    GET  /soumissions/{id}/avenants          → liste + impact
    POST /soumissions/{id}/avenants          → crée AV-n et applique
                                               ses opérations

Opérations d'un avenant :
- ``ajout``        : nouvel item au contrat (marqué avenant_id) ;
- ``retrait``      : item existant retiré du contrat courant — JAMAIS
                     supprimé (son « facturé à date » reste attaché) ;
- ``modification`` : prix / quantité / description d'un item existant,
                     avec avant/après journalisés dans l'avenant.

Après application : totaux de la soumission recalculés (items retirés
exclus) → le contrat courant devient la base de la facturation
progressive. Si un item modifié/retiré a déjà été facturé au-delà de
son nouveau montant, la réponse le signale (crédit à prévoir).
"""

import json
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.models.facture import Facture
from app.models.facture_item import FactureItem
from app.models.soumission import Soumission
from app.models.soumission_avenant import SoumissionAvenant
from app.models.soumission_item import SoumissionItem

router = APIRouter(prefix="/soumissions", tags=["soumission-avenants"])


class AvenantOperation(BaseModel):
    op: Literal["ajout", "retrait", "modification"]
    #: retrait / modification : l'item visé.
    item_id: Optional[int] = None
    #: ajout / modification : les champs de la ligne.
    description: Optional[str] = Field(default=None, max_length=4000)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    cost_per_unit: Optional[float] = Field(default=None, ge=0)
    #: Ventilation du coûtant comme sur le devis (2026-09-30) ; la somme
    #: alimente cost_per_unit.
    cost_labor_per_unit: Optional[float] = Field(default=None, ge=0)
    cost_material_per_unit: Optional[float] = Field(default=None, ge=0)


def _cout_total(op: "AvenantOperation", base: Optional[float] = None) -> Optional[float]:
    """cost_per_unit = M.O. + matériaux quand l'un des deux est donné,
    sinon cost_per_unit tel quel, sinon ``base`` (inchangé)."""
    if op.cost_labor_per_unit is not None or op.cost_material_per_unit is not None:
        return round(float(op.cost_labor_per_unit or 0) + float(op.cost_material_per_unit or 0), 2)
    if op.cost_per_unit is not None:
        return float(op.cost_per_unit)
    return base


class AvenantCreate(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)
    operations: List[AvenantOperation] = Field(..., min_length=1, max_length=50)


class AvenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    soumission_id: int
    numero: int
    reference: str
    note: Optional[str]
    changes_json: Optional[str]
    impact_subtotal: float
    created_by_email: Optional[str]
    created_at: Optional[object] = None
    #: Signature client (2026-09-30) : interne | envoye | signe | refuse.
    signature_status: str = "interne"
    sent_at: Optional[datetime] = None
    sent_to: Optional[str] = None
    client_opened_at: Optional[datetime] = None
    signed_at: Optional[datetime] = None
    signed_name: Optional[str] = None
    declined_at: Optional[datetime] = None
    decline_reason: Optional[str] = None


class AvenantSendRequest(BaseModel):
    to: List[EmailStr] = Field(..., min_length=1)
    cc: Optional[List[EmailStr]] = None
    message: Optional[str] = Field(default=None, max_length=4000)


class AvenantResult(BaseModel):
    avenant: AvenantRead
    #: Nouveau sous-total HT du contrat courant.
    contrat_courant: float
    #: Items dont le « facturé à date » dépasse le nouveau montant au
    #: contrat — un crédit est à prévoir (libellés lisibles).
    surfactures: List[str] = []


async def _facture_a_date_par_item(db, item_ids: list[int]) -> dict[int, float]:
    """$ HT déjà facturé (factures non annulées) par item de devis."""
    if not item_ids:
        return {}
    rows = (
        await db.execute(
            select(
                FactureItem.soumission_item_id,
                func.coalesce(func.sum(FactureItem.total), 0),
            )
            .join(Facture, Facture.id == FactureItem.facture_id)
            .where(
                FactureItem.soumission_item_id.in_(item_ids),
                Facture.status != "void",
            )
            .group_by(FactureItem.soumission_item_id)
        )
    ).all()
    return {int(sid): round(float(tot or 0), 2) for sid, tot in rows}


@router.get(
    "/{soumission_id}/avenants",
    response_model=List[AvenantRead],
    summary="Avenants du devis (change orders)",
)
async def list_avenants(
    soumission_id: int, db: DBSession, _: CurrentUser
) -> List[AvenantRead]:
    rows = (
        await db.execute(
            select(SoumissionAvenant)
            .where(SoumissionAvenant.soumission_id == soumission_id)
            .order_by(SoumissionAvenant.numero.asc())
        )
    ).scalars().all()
    return [AvenantRead.model_validate(r) for r in rows]


@router.post(
    "/{soumission_id}/avenants",
    response_model=AvenantResult,
    status_code=status.HTTP_201_CREATED,
    summary="Crée un avenant et applique ses opérations au contrat",
)
async def create_avenant(
    soumission_id: int,
    data: AvenantCreate,
    db: DBSession,
    user: CurrentUser,
) -> AvenantResult:
    sm = (
        await db.execute(
            select(Soumission).where(Soumission.id == soumission_id)
        )
    ).scalar_one_or_none()
    if sm is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Soumission introuvable."
        )
    if sm.status != "accepted":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Les avenants s'appliquent à un devis ACCEPTÉ — avant "
            "l'acceptation, modifiez le devis directement.",
        )

    items = {
        it.id: it
        for it in (
            await db.execute(
                select(SoumissionItem).where(
                    SoumissionItem.soumission_id == soumission_id
                )
            )
        ).scalars().all()
    }
    max_pos = max((it.position for it in items.values()), default=-1)

    # Validation d'abord — un avenant s'applique en entier ou pas du tout.
    for op in data.operations:
        if op.op in ("retrait", "modification"):
            it = items.get(int(op.item_id or 0))
            if it is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    f"Item #{op.item_id} introuvable sur ce devis.",
                )
            if it.retire_par_avenant_id is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"L'item « {it.description[:60]} » a déjà été retiré "
                    "par un avenant précédent.",
                )
        if op.op == "ajout" and not (op.description or "").strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Un ajout doit avoir une description.",
            )
        if op.op == "modification" and not any(
            v is not None
            for v in (
                op.description, op.unit, op.quantity, op.unit_price,
                op.cost_per_unit, op.cost_labor_per_unit, op.cost_material_per_unit,
            )
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Une modification doit changer au moins un champ.",
            )

    numero = (
        (
            await db.execute(
                select(func.coalesce(func.max(SoumissionAvenant.numero), 0))
                .where(SoumissionAvenant.soumission_id == soumission_id)
            )
        ).scalar_one()
        + 1
    )
    av = SoumissionAvenant(
        soumission_id=soumission_id,
        numero=numero,
        reference=f"AV-{numero}",
        note=(data.note or "").strip() or None,
        created_by_email=getattr(user, "email", None),
    )
    db.add(av)
    await db.flush()

    def _snapshot(it: SoumissionItem) -> dict:
        return {
            "description": it.description,
            "unit": it.unit,
            "quantity": float(it.quantity or 0),
            "unit_price": float(it.unit_price or 0),
            "total": float(it.total or 0),
        }

    changes: list[dict] = []
    impact = 0.0
    pos = max_pos + 1
    for op in data.operations:
        if op.op == "ajout":
            qty = float(op.quantity if op.quantity is not None else 1)
            price = float(op.unit_price or 0)
            it = SoumissionItem(
                soumission_id=soumission_id,
                position=pos,
                description=(op.description or "").strip(),
                unit=(op.unit or None),
                quantity=qty,
                unit_price=price,
                cost_per_unit=float(_cout_total(op) or 0),
                cost_labor_per_unit=op.cost_labor_per_unit,
                cost_material_per_unit=op.cost_material_per_unit,
                total=round(qty * price, 2),
                avenant_id=av.id,
            )
            pos += 1
            db.add(it)
            await db.flush()
            impact += float(it.total or 0)
            changes.append(
                {"op": "ajout", "item_id": it.id, "apres": _snapshot(it)}
            )
        elif op.op == "retrait":
            it = items[int(op.item_id)]
            it.retire_par_avenant_id = av.id
            impact -= float(it.total or 0)
            changes.append(
                {"op": "retrait", "item_id": it.id, "avant": _snapshot(it)}
            )
        else:  # modification
            it = items[int(op.item_id)]
            avant = _snapshot(it)
            if op.description is not None and op.description.strip():
                it.description = op.description.strip()
            if op.unit is not None:
                it.unit = op.unit or None
            if op.quantity is not None:
                it.quantity = float(op.quantity)
            if op.unit_price is not None:
                it.unit_price = float(op.unit_price)
            if op.cost_labor_per_unit is not None:
                it.cost_labor_per_unit = float(op.cost_labor_per_unit)
            if op.cost_material_per_unit is not None:
                it.cost_material_per_unit = float(op.cost_material_per_unit)
            if op.cost_labor_per_unit is not None or op.cost_material_per_unit is not None:
                it.cost_per_unit = round(
                    float(it.cost_labor_per_unit or 0) + float(it.cost_material_per_unit or 0), 2
                )
            elif op.cost_per_unit is not None:
                it.cost_per_unit = float(op.cost_per_unit)
            it.total = round(float(it.quantity) * float(it.unit_price), 2)
            impact += float(it.total or 0) - avant["total"]
            changes.append(
                {
                    "op": "modification",
                    "item_id": it.id,
                    "avant": avant,
                    "apres": _snapshot(it),
                }
            )

    av.changes_json = json.dumps(changes, ensure_ascii=False)
    av.impact_subtotal = round(impact, 2)
    await db.flush()

    # Totaux du contrat courant (items retirés exclus) + budget projets.
    from app.api.v1.endpoints.soumission_items import (
        _recompute_soumission_totals,
    )

    await _recompute_soumission_totals(db, soumission_id)
    await db.refresh(sm)

    # Sur-facturation : items touchés dont le facturé à date dépasse le
    # nouveau montant au contrat → crédit à prévoir, signalé tout de suite.
    touched = [
        c["item_id"] for c in changes if c["op"] in ("retrait", "modification")
    ]
    billed = await _facture_a_date_par_item(db, touched)
    surfactures: list[str] = []
    for c in changes:
        iid = c["item_id"]
        b = billed.get(iid, 0.0)
        au_contrat = (
            0.0 if c["op"] == "retrait" else c.get("apres", {}).get("total", 0.0)
        )
        if b - au_contrat > 0.01:
            it = items.get(iid)
            surfactures.append(
                f"« {(it.description if it else str(iid))[:80]} » : "
                f"{b:.2f} $ déjà facturé pour {au_contrat:.2f} $ au "
                f"contrat — crédit de {b - au_contrat:.2f} $ à prévoir."
            )

    return AvenantResult(
        avenant=AvenantRead.model_validate(av),
        contrat_courant=float(sm.subtotal or 0),
        surfactures=surfactures,
    )


# ───────────── Signature de l'avenant par le client (2026-09-30) ─────────────


async def _avenant_du_devis(db, soumission_id: int, avenant_id: int) -> SoumissionAvenant:
    av = (
        await db.execute(
            select(SoumissionAvenant).where(
                SoumissionAvenant.id == avenant_id,
                SoumissionAvenant.soumission_id == soumission_id,
            )
        )
    ).scalar_one_or_none()
    if av is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Avenant introuvable.")
    return av


@router.get(
    "/{soumission_id}/avenants/{avenant_id}/pdf",
    summary="PDF de l'avenant (signé si le client l'a signé)",
)
async def avenant_pdf(soumission_id: int, avenant_id: int, db: DBSession, _: CurrentUser) -> Response:
    from app.services.avenant_pdf import avenant_pdf_filename, render_avenant_pdf

    av = await _avenant_du_devis(db, soumission_id, avenant_id)
    if av.signature_status == "signe":
        blob = (
            await db.execute(
                select(SoumissionAvenant.signed_pdf_blob).where(SoumissionAvenant.id == av.id)
            )
        ).scalar_one_or_none()
        if blob:
            sm = (await db.execute(select(Soumission).where(Soumission.id == soumission_id))).scalar_one()
            return Response(
                content=bytes(blob), media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="{avenant_pdf_filename(av, sm, signe=True)}"'},
            )
    rendered = await render_avenant_pdf(db, av.id)
    if rendered is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Avenant introuvable.")
    av, sm, pdf = rendered
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{avenant_pdf_filename(av, sm)}"'},
    )


@router.post(
    "/{soumission_id}/avenants/{avenant_id}/envoyer",
    response_model=AvenantRead,
    summary="Envoie l'avenant au client pour signature (PDF + lien public)",
)
async def envoyer_avenant(
    soumission_id: int, avenant_id: int, data: AvenantSendRequest, db: DBSession, _: CurrentUser
) -> AvenantRead:
    from app.services.avenant_send import AvenantSendError, send_avenant

    await _avenant_du_devis(db, soumission_id, avenant_id)
    try:
        av = await send_avenant(
            db, avenant_id, to=[str(a) for a in data.to], cc=[str(a) for a in (data.cc or [])],
            message=data.message,
        )
    except AvenantSendError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AvenantRead.model_validate(av)


@router.get(
    "/{soumission_id}/documents-signes",
    summary="PDF signés du contrat dans l'ordre : original puis avenants",
)
async def documents_signes(soumission_id: int, db: DBSession, _: CurrentUser) -> list[dict]:
    sm = (await db.execute(select(Soumission).where(Soumission.id == soumission_id))).scalar_one_or_none()
    if sm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Soumission introuvable.")
    out: list[dict] = []
    if sm.status == "accepted":
        out.append({
            "kind": "original", "reference": sm.reference, "label": f"Soumission {sm.reference} (original signé)",
            "signed_name": sm.signed_name, "signed_at": (sm.accepted_at.isoformat() if sm.accepted_at else None),
            "pdf_path": f"/api/v1/soumissions/{sm.id}/pdf",
        })
    rows = (
        await db.execute(
            select(SoumissionAvenant).where(SoumissionAvenant.soumission_id == soumission_id)
            .order_by(SoumissionAvenant.numero.asc())
        )
    ).scalars().all()
    for av in rows:
        out.append({
            "kind": "avenant", "reference": av.reference,
            "label": f"Avenant {av.reference}" + (" (signé)" if av.signature_status == "signe" else f" ({av.signature_status})"),
            "status": av.signature_status, "signed_name": av.signed_name,
            "signed_at": (av.signed_at.isoformat() if av.signed_at else None),
            "pdf_path": f"/api/v1/soumissions/{sm.id}/avenants/{av.id}/pdf",
        })
    return out
