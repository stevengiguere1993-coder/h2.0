"""Create a Facture from a Project.

Pre-fills client, pulls the Project description, and optionally
seeds the line items from the project's approved (or all) punches —
grouped by employee × hourly_rate.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.api.v1.endpoints.facture_import import _compute_billed_amount
from app.models.achat import Achat
from app.models.employe import Employe
from app.models.facture import Facture, FactureStatus
from app.models.facture_item import FactureItem
from app.models.project import Project
from app.models.project_subcontractor_contract import (
    ProjectSubcontractorContract,
)
from app.models.punch import Punch
from app.models.soumission import Soumission, SoumissionStatus
from app.models.soumission_item import SoumissionItem
from app.schemas.business import FactureRead
from app.services.numbering import next_facture_number


router = APIRouter(prefix="/projects", tags=["project-to-facture"])


class ConvertToFactureRequest(BaseModel):
    include_soumission: bool = Field(
        default=False,
        description=(
            "Seed line items from the accepted soumission linked to "
            "this project (prix fixe)."
        ),
    )
    soumission_percentage: float = Field(
        default=100, ge=1, le=100,
        description=(
            "Pourcentage cumulatif visé de la soumission à facturer "
            "(progressive billing par défaut : soustrait ce qui a déjà "
            "été facturé pour ce projet). Ex. déjà facturé 30 %, "
            "demande 90 % → la nouvelle facture sera de 60 %."
        ),
    )
    soumission_amount: Optional[float] = Field(
        default=None, ge=0,
        description=(
            "Montant fixe $ à facturer (avant taxes). Surcharge "
            "soumission_percentage. En mode progressive (défaut), "
            "représente le total cumulatif visé — la nouvelle facture "
            "couvrira (montant - déjà facturé)."
        ),
    )
    progressive_billing: bool = Field(
        default=True,
        description=(
            "Si True (défaut), soumission_percentage et "
            "soumission_amount sont CUMULATIFS — on soustrait ce qui a "
            "déjà été facturé pour ce projet pour éviter de double-"
            "facturer. Si False, on facture le % ou le $ tel quel "
            "(ancien comportement)."
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
    # Phase A — refacturation des achats avec markup et traçabilité.
    achat_ids: Optional[list[int]] = Field(
        default=None,
        description=(
            "Si fourni, restreint les achats importés à cette liste. "
            "Sinon, tous les achats refacturables non encore facturés "
            "du projet."
        ),
    )
    achat_markup_overrides: dict[int, float] = Field(
        default_factory=dict,
        description=(
            "Markup à appliquer par achat (achat_id -> %). Surcharge "
            "Achat.markup_percent ; 0 si non renseigné."
        ),
    )
    due_in_days: Optional[int] = Field(
        default=0, ge=0, le=365,
        description=(
            "Jours avant l'échéance. 0 (défaut) = « Payable sur "
            "réception »."
        ),
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
        reference=await next_facture_number(db),
        client_id=project.client_id,
        project_id=project.id,
        status=FactureStatus.DRAFT.value,
        # issued_at reste vide : la facture n'est « émise » qu'à l'envoi
        # au client, pas à sa création (cf. send_facture).
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

            # Base HT de référence pour la facturation par étapes. On la
            # recalcule depuis les ITEMS (somme des lignes de vente HT) et
            # NON depuis sm.subtotal STOCKÉ : ce dernier peut avoir dérivé
            # vers un montant TAXES INCLUSES (même cause que le KPI projet).
            # Si la base était en échelle TTC alors que le « déjà facturé »
            # (already_billed) est en HT, la cible cumulative et les ratios
            # seraient faux → sur-facturation en facturation progressive.
            sm_base = round(sum(float(it.total or 0) for it in sm_items), 2)
            if sm_base <= 0:
                sm_base = float(sm.subtotal or 0)

            # Progressive billing PAR ITEM : combien a déjà été facturé
            # pour ce projet au titre de la soumission de base, ITEM PAR
            # ITEM (lignes liées via soumission_item_id). Un item chargé
            # AU COMPLET sur une facture précédente ne réapparaît plus ;
            # un item chargé partiellement n'est facturé que du restant.
            # Les lignes « extra » (T&M, achats hors-contrat) sont
            # exclues : elles ne réduisent pas la cible du devis. Le
            # montant non attribuable à un item (acompte global, factures
            # antérieures au lien par item) est réparti au prorata du
            # poids de chaque item — même effet global qu'avant.
            linked_billed: dict[int, float] = {}
            unattributed_billed = 0.0
            if data.progressive_billing:
                from app.models.facture import Facture as _Fac

                prev_ids = (
                    await db.execute(
                        select(_Fac.id).where(
                            _Fac.project_id == project_id,
                            _Fac.id != facture.id,
                        )
                    )
                ).scalars().all()
                if prev_ids:
                    rows = (
                        await db.execute(
                            select(
                                FactureItem.soumission_item_id,
                                func.coalesce(
                                    func.sum(FactureItem.total), 0
                                ),
                            )
                            .where(
                                FactureItem.facture_id.in_(prev_ids),
                                FactureItem.kind != "extra",
                            )
                            .group_by(FactureItem.soumission_item_id)
                        )
                    ).all()
                    for sid, amt in rows:
                        if sid is None:
                            unattributed_billed = round(float(amt or 0), 2)
                        else:
                            linked_billed[int(sid)] = round(
                                float(amt or 0), 2
                            )
            already_billed = round(
                unattributed_billed + sum(linked_billed.values()), 2
            )

            # Détermine le ratio cible cumulatif.
            if data.soumission_amount is not None and data.soumission_amount > 0:
                target_amount = float(data.soumission_amount)
                prefix_value = target_amount
                prefix_kind = "amount"
            else:
                target_pct = max(1.0, min(100.0, float(data.soumission_percentage)))
                target_amount = sm_base * (target_pct / 100.0)
                prefix_value = float(target_pct)
                prefix_kind = "pct"

            # Ratio cible cumulatif, borné à 100 % : on ne charge jamais
            # un item au-delà de son montant de soumission.
            target_ratio = (
                min(1.0, target_amount / sm_base) if sm_base > 0 else 1.0
            )

            delta_amount = 0.0
            planned: list[tuple[SoumissionItem, float]] = []
            for it in sm_items:
                item_total = float(it.total or 0)
                if item_total <= 0:
                    continue
                share = (item_total / sm_base) if sm_base > 0 else 0.0
                billed_i = (
                    linked_billed.get(int(it.id), 0.0)
                    + unattributed_billed * share
                )
                if not data.progressive_billing:
                    billed_i = 0.0
                remaining_i = max(0.0, item_total - billed_i)
                target_i = item_total * target_ratio
                delta_i = round(
                    min(max(0.0, target_i - billed_i), remaining_i), 2
                )
                if delta_i <= 0.01:
                    # Item déjà chargé au complet (ou cible atteinte) →
                    # il n'apparaît PAS sur cette facture.
                    continue
                planned.append((it, delta_i))
                delta_amount += delta_i
            delta_amount = round(delta_amount, 2)

            if not planned and sm_base > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cible cumulative ({target_amount:.2f} $) déjà "
                        f"atteinte ou dépassée par les factures "
                        f"existantes ({already_billed:.2f} $). Rien à "
                        f"facturer cette fois."
                    ),
                )

            ratio = (delta_amount / sm_base) if sm_base > 0 else 1.0
            pct = max(1, min(100, round(ratio * 100)))

            if prefix_kind == "amount":
                prefix = f"{int(round(prefix_value))} $ — "
            else:
                prefix = f"{prefix_value:g}% — " if pct != 100 else ""
            for it, delta_i in planned:
                item_total = float(it.total or 0)
                if abs(delta_i - item_total) <= 0.01 and float(it.quantity) > 0:
                    # Item chargé au complet → quantité/prix/unité d'origine.
                    qty = float(it.quantity)
                    unit = it.unit
                    unit_price = float(it.unit_price)
                    line_total = round(qty * unit_price, 2)
                else:
                    # Partiel → une ligne « lot » au montant exact de la
                    # tranche (qty 1), pour éviter la dérive d'arrondi
                    # quantité × prix et ne pas afficher une fausse
                    # quantité au client.
                    qty = 1.0
                    unit = "lot"
                    unit_price = delta_i
                    line_total = delta_i
                db.add(
                    FactureItem(
                        facture_id=facture.id,
                        position=pos,
                        description=f"{prefix}{it.description}",
                        unit=unit,
                        quantity=qty,
                        unit_price=unit_price,
                        total=line_total,
                        soumission_item_id=int(it.id),
                    )
                )
                pos += 1

    # 2) T&M — heures punchées approuvées (non encore facturées) au
    #    `billing_rate` de l'employé (fallback hourly_rate), groupées
    #    par (employé, taux). Marquage des punches après création.
    if data.include_hours:
        stmt = select(Punch).where(Punch.project_id == project_id)
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
                    await db.execute(
                        select(Employe).where(Employe.id.in_(emp_ids))
                    )
                ).scalars().all()
            }

            # UNE SEULE ligne « Main-d'œuvre » totale sur la facture
            # client : toutes les heures additionnées, AUCUN nom d'employé
            # (le client ne doit pas les voir). Prix unitaire = moyenne
            # pondérée des taux, pour que le total reste exact.
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
                    facture_id=facture.id,
                    position=pos,
                    description="Main-d'œuvre",
                    unit="h",
                    quantity=total_hours,
                    unit_price=unit_price,
                    total=total_amount,
                    # Heures T&M = hors soumission de base → extra.
                    kind="extra",
                )
                db.add(item)
                pos += 1
                await db.flush()
                from datetime import datetime as _dt2, timezone as _tz2
                now_h = _dt2.now(_tz2.utc)
                for p in punches:
                    p.invoiced_at = now_h
                    p.facture_item_id = item.id

    # 3) Achats — refacturation avec markup OU contrat sous-traitant et
    #    flag anti-doublon. Seuls les achats `is_billable=True` non
    #    encore facturés sont importés.
    if data.include_achats:
        stmt = (
            select(Achat)
            .where(Achat.project_id == project_id)
            .where(Achat.is_billable.is_(True))
            .where(Achat.invoiced_at.is_(None))
            .order_by(Achat.id.asc())
        )
        if data.achat_ids:
            stmt = stmt.where(Achat.id.in_(data.achat_ids))
        achats = (await db.execute(stmt)).scalars().all()

        sub_ids = {a.sous_traitant_id for a in achats if a.sous_traitant_id}
        contracts_by_st: dict[int, ProjectSubcontractorContract] = {}
        if sub_ids:
            ctr_rows = (
                await db.execute(
                    select(ProjectSubcontractorContract)
                    .where(
                        ProjectSubcontractorContract.project_id == project_id
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
            # La majoration / règle de facturation (`rule_label`) est
            # INTERNE : on l'applique au montant (`billed`) mais on ne
            # l'affiche JAMAIS dans la description vue par le client.
            desc = base_desc
            contract = (
                contracts_by_st.get(ac.sous_traitant_id or 0)
                if ac.kind == "sub_invoice"
                else None
            )
            if contract is not None and contract.billing_mode == "flat_hourly":
                unit = "h"
                qty = float(ac.hours or 0)
                up = float(contract.flat_hourly_rate or 0)
            else:
                unit = "lot"
                qty = 1
                up = billed
            item = FactureItem(
                facture_id=facture.id,
                position=pos,
                description=f"{line_prefix} — {desc}",
                unit=unit,
                quantity=qty,
                unit_price=up,
                total=billed,
                # Achats / matériel / sous-traitant = hors soumission de
                # base → extra (ne compte pas dans la cible cumulative).
                kind="extra",
            )
            db.add(item)
            new_items.append((ac, item))
            pos += 1

        await db.flush()
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc)
        for ac, item in new_items:
            ac.invoiced_at = now
            ac.facture_item_id = item.id

    await db.flush()
    # Recompute totaux facture depuis les items qu'on vient de créer
    # (subtotal / tps / tvq / total). Sans ça, Facture.total reste à
    # NULL → KPI projet « Facturé » affiche 0 $ même après création.
    from app.api.v1.endpoints.facture_items import _recompute_facture_totals

    await _recompute_facture_totals(db, facture.id)
    await db.refresh(facture)
    return FactureRead.model_validate(facture)
