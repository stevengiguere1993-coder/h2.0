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
from app.models.project_subcontractor_contract import (
    ProjectSubcontractorContract,
)
from app.models.punch import Punch
from app.models.soumission import Soumission, SoumissionStatus
from app.models.soumission_item import SoumissionItem


def _compute_billed_amount(
    ac: Achat,
    markup_overrides: dict[int, float],
    contracts_by_st: dict[int, ProjectSubcontractorContract],
) -> tuple[float, str]:
    """Calcule le montant à facturer + un label décrivant la règle
    appliquée. Centralise la logique pour les deux endpoints d'import."""
    cost = float(ac.amount or 0)
    if ac.kind == "sub_invoice" and ac.sous_traitant_id:
        contract = contracts_by_st.get(ac.sous_traitant_id)
        if contract is not None:
            if contract.billing_mode == "markup_pct":
                m = float(contract.markup_percent or 0)
                return round(cost * (1 + m / 100.0), 2), f"contrat +{m:g} %"
            if contract.billing_mode == "flat_hourly":
                rate = float(contract.flat_hourly_rate or 0)
                hours = float(ac.hours or 0)
                return round(hours * rate, 2), f"contrat {rate:g} $/h × {hours:g} h"
            if contract.billing_mode == "lump_sum":
                amt = float(contract.lump_sum_amount or 0)
                return round(amt, 2), "contrat forfait"
        # Pas de contrat sous-traitant → on retombe sur la majoration
        # MANUELLE de l'achat (comme un achat matériel), pour pouvoir
        # facturer une facture de sous-traitant avec un markup ajustable.
        # (fall-through vers le calcul markup ci-dessous)
    # Achat matériel OU sous-traitant sans contrat — markup individuel.
    # Priorité : override à l'import > markup_percent de l'achat > défaut
    # 10 % (NULL = non saisi → 10 % ; 0 = coûtant volontaire).
    _base_markup = (
        float(ac.markup_percent) if ac.markup_percent is not None else 10.0
    )
    pct = float(markup_overrides.get(ac.id, _base_markup))
    return round(cost * (1 + pct / 100.0), 2), (
        f"+{pct:g} %" if pct > 0 else "coûtant"
    )


router = APIRouter(prefix="/factures", tags=["facture-import"])


class ImportRequest(BaseModel):
    include_soumission: bool = False
    soumission_percentage: float = Field(default=100, ge=1, le=100)
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
                pct = max(1.0, min(100.0, float(data.soumission_percentage)))
                ratio = pct / 100.0
                prefix = f"{pct:g}% — " if pct != 100 else ""
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

    # 2) Heures punchées — facturées au `billing_rate` de l'employé
    #    (fallback `hourly_rate` si non défini). Punches déjà facturés
    #    ignorés. Marquage des punches après création des items pour
    #    traçabilité et garde-fou anti-doublon.
    if data.include_hours and fa.project_id:
        stmt = select(Punch).where(Punch.project_id == fa.project_id)
        if data.only_approved:
            stmt = stmt.where(Punch.approved.is_(True))
        stmt = stmt.where(Punch.hours.is_not(None))
        stmt = stmt.where(Punch.invoiced_at.is_(None))
        punches = (await db.execute(stmt)).scalars().all()
        if punches:
            emp_ids = {p.employe_id for p in punches}
            emps = {
                e.id: e
                for e in (
                    await db.execute(select(Employe).where(Employe.id.in_(emp_ids)))
                ).scalars().all()
            }
            # UNE SEULE ligne « Main-d'œuvre » totale (toutes les heures
            # additionnées, AUCUN nom d'employé sur la facture client).
            # Prix unitaire = moyenne pondérée des taux pour garder le
            # total exact.
            total_hours = 0.0
            total_amount = 0.0
            for p in punches:
                emp = emps.get(p.employe_id)
                if emp and emp.billing_rate is not None:
                    rate = float(emp.billing_rate)
                elif emp and emp.hourly_rate:
                    rate = float(emp.hourly_rate)
                else:
                    rate = 0.0
                h = float(p.hours or 0)
                total_hours += h
                total_amount += h * rate
            total_hours = round(total_hours, 2)
            total_amount = round(total_amount, 2)

            if total_hours > 0:
                unit_price = round(total_amount / total_hours, 2)
                item = FactureItem(
                    facture_id=fa.id,
                    position=pos,
                    description="Main-d'œuvre",
                    unit="h",
                    quantity=total_hours,
                    unit_price=unit_price,
                    total=total_amount,
                    kind="extra",
                )
                db.add(item)
                pos += 1
                added += 1
                await db.flush()
                now = datetime.now(timezone.utc)
                for p in punches:
                    p.invoiced_at = now
                    p.facture_item_id = item.id

    # 3) Achats — refacturation avec markup OU contrat sous-traitant et
    #    flag anti-doublon. On ne tire QUE les achats refacturables non
    #    encore facturés (invoiced_at IS NULL).
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

        # Pré-charge les contrats sous-traitants du projet pour les
        # achats de type sub_invoice. Un seul round-trip.
        sub_ids = {a.sous_traitant_id for a in achats if a.sous_traitant_id}
        contracts_by_st: dict[int, ProjectSubcontractorContract] = {}
        if sub_ids:
            ctr_rows = (
                await db.execute(
                    select(ProjectSubcontractorContract)
                    .where(
                        ProjectSubcontractorContract.project_id == fa.project_id
                    )
                    .where(
                        ProjectSubcontractorContract.sous_traitant_id.in_(sub_ids)
                    )
                )
            ).scalars().all()
            contracts_by_st = {c.sous_traitant_id: c for c in ctr_rows}

        new_items: list[tuple[Achat, FactureItem]] = []
        for ac in achats:
            billed, _rule_label = _compute_billed_amount(
                ac, data.achat_markup_overrides, contracts_by_st
            )
            base_desc = ac.description or f"Achat {ac.reference or ac.id}"
            line_prefix = (
                "Sous-traitant" if ac.kind == "sub_invoice" else "Matériel"
            )
            # La majoration / règle (`rule_label`) est INTERNE : appliquée
            # au montant mais jamais affichée dans la description client.
            desc = base_desc
            item = FactureItem(
                facture_id=fa.id,
                position=pos,
                description=f"{line_prefix} — {desc}",
                unit="h" if (
                    ac.kind == "sub_invoice"
                    and contracts_by_st.get(ac.sous_traitant_id or 0)
                    and contracts_by_st[ac.sous_traitant_id].billing_mode
                    == "flat_hourly"
                ) else "lot",
                quantity=(
                    float(ac.hours or 0)
                    if ac.kind == "sub_invoice"
                    and contracts_by_st.get(ac.sous_traitant_id or 0)
                    and contracts_by_st[ac.sous_traitant_id].billing_mode
                    == "flat_hourly"
                    else 1
                ),
                unit_price=(
                    float(
                        contracts_by_st[ac.sous_traitant_id].flat_hourly_rate
                        or 0
                    )
                    if ac.kind == "sub_invoice"
                    and contracts_by_st.get(ac.sous_traitant_id or 0)
                    and contracts_by_st[ac.sous_traitant_id].billing_mode
                    == "flat_hourly"
                    else billed
                ),
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
    # Regroupe les lignes importées par type (service → extra → frais
    # → rabais) — cohérent avec l'ajout manuel.
    from app.api.v1.endpoints.facture_items import _reorder_items_by_kind

    await _reorder_items_by_kind(db, facture_id)
    return ImportResult(added=added)
