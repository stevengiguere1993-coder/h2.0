"""Vue « à refacturer » par projet.

Liste toutes les sources potentielles de refacturation pour un projet
qui n'ont pas encore été versées sur une facture client. Sert à
alimenter l'onglet « À refacturer » de la page projet et le sélecteur
d'import dans le flux de création de facture.

Phase A : achats refacturables non facturés.
Phase B : punches non facturés (heures × billing_rate).
Phase C (à venir) : factures de sous-traitants non refacturées.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.achat import Achat
from app.models.employe import Employe
from app.models.fournisseur import Fournisseur
from app.models.project import Project
from app.models.punch import Punch


router = APIRouter(prefix="/projects", tags=["project-billables"])


class BillableAchat(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reference: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    markup_percent: Optional[float] = None
    fournisseur_id: Optional[int] = None
    fournisseur_name: Optional[str] = None
    supplier_invoice_number: Optional[str] = None
    # Montant projeté qui sera facturé au client (cost × (1 + markup/100)).
    projected_billed_amount: float = 0.0
    # False = achat non marqué refacturable (défaut des projets estimés /
    # forfaitaires). Retourné seulement avec include_non_billable=true ;
    # le sélectionner à l'import le marque refacturable.
    is_billable: bool = True
    # Renseignés seulement avec include_invoiced=true : achat DÉJÀ versé
    # sur une facture (non sélectionnable — affiché pour que l'absence
    # d'un achat dans le sélecteur ne soit jamais un mystère).
    invoiced_at: Optional[str] = None
    invoiced_facture_reference: Optional[str] = None


class BillablePunchBucket(BaseModel):
    """Regroupe les heures non facturées d'un employé à son taux
    facturable. Représente une future ligne de facture."""

    model_config = ConfigDict(from_attributes=True)

    employe_id: int
    employe_name: str
    billing_rate: float
    hours: float
    projected_amount: float
    punch_count: int


class BillablesSummary(BaseModel):
    achats: List[BillableAchat]
    punch_buckets: List[BillablePunchBucket] = []
    total_cost: float
    total_projected: float
    count: int
    total_hours: float = 0.0
    total_hours_projected: float = 0.0


@router.get(
    "/{project_id}/billables",
    response_model=BillablesSummary,
    summary="Liste tout ce qui reste à refacturer pour le projet",
)
async def list_billables(
    project_id: int,
    db: DBSession,
    _: CurrentUser,
    include_non_billable: bool = False,
    include_invoiced: bool = False,
) -> BillablesSummary:
    """`include_non_billable=true` : liste AUSSI les achats non marqués
    refacturables (défaut des projets estimés / forfaitaires) pour que le
    sélecteur d'import de facture puisse les proposer — les sélectionner
    à l'import les marque refacturables. `include_invoiced=true` : liste
    aussi les achats DÉJÀ facturés (avec le numéro de leur facture) pour
    que l'absence d'un achat ne soit jamais un mystère. Les totaux ne
    comptent que les refacturables non facturés (l'onglet « À
    refacturer » du projet reste inchangé)."""
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    stmt = (
        select(Achat)
        .where(Achat.project_id == project_id)
        .order_by(Achat.id.asc())
    )
    if not include_invoiced:
        stmt = stmt.where(Achat.invoiced_at.is_(None))
    if not include_non_billable:
        stmt = stmt.where(Achat.is_billable.is_(True))
    achats = (await db.execute(stmt)).scalars().all()

    # Numéro de facture des achats déjà facturés (facture_item → facture),
    # en un seul round-trip.
    facture_ref_by_item: dict[int, str] = {}
    _invoiced_item_ids = {
        a.facture_item_id
        for a in achats
        if a.invoiced_at is not None and a.facture_item_id
    }
    if _invoiced_item_ids:
        from app.models.facture import Facture
        from app.models.facture_item import FactureItem

        rows = (
            await db.execute(
                select(FactureItem.id, Facture.reference)
                .join(Facture, Facture.id == FactureItem.facture_id)
                .where(FactureItem.id.in_(_invoiced_item_ids))
            )
        ).all()
        facture_ref_by_item = {iid: ref for iid, ref in rows}

    # Résolution des noms de fournisseurs en un seul round-trip.
    fourn_ids = {a.fournisseur_id for a in achats if a.fournisseur_id}
    fourn_names: dict[int, str] = {}
    if fourn_ids:
        rows = (
            await db.execute(
                select(Fournisseur.id, Fournisseur.name).where(
                    Fournisseur.id.in_(fourn_ids)
                )
            )
        ).all()
        fourn_names = {fid: name for fid, name in rows}

    items: List[BillableAchat] = []
    total_cost = 0.0
    total_projected = 0.0
    for a in achats:
        cost = float(a.amount or 0)
        # Majoration par défaut 10 % quand non saisie (NULL) ; 0 = coûtant.
        markup = (
            float(a.markup_percent) if a.markup_percent is not None else 10.0
        )
        projected = round(cost * (1 + markup / 100.0), 2)
        if a.is_billable and a.invoiced_at is None:
            total_cost += cost
            total_projected += projected
        items.append(
            BillableAchat(
                id=a.id,
                reference=a.reference,
                description=a.description,
                amount=cost,
                # Renvoie la majoration effective (10 % par défaut) pour
                # qu'elle s'affiche et s'applique à l'import.
                markup_percent=markup,
                fournisseur_id=a.fournisseur_id,
                fournisseur_name=fourn_names.get(a.fournisseur_id or 0),
                supplier_invoice_number=a.supplier_invoice_number,
                projected_billed_amount=projected,
                is_billable=bool(a.is_billable),
                invoiced_at=(
                    a.invoiced_at.isoformat() if a.invoiced_at else None
                ),
                invoiced_facture_reference=facture_ref_by_item.get(
                    a.facture_item_id or 0
                ),
            )
        )

    # Phase B — heures non facturées, regroupées par employé × taux
    # facturable (mirror du regroupement à l'import). MÊME périmètre que
    # l'import (facture_import) : heures du projet + heures pointées
    # DIRECTEMENT sur un bon de travail lié à ce projet
    # (punch.bon_travail_id sans project_id — bons pointés du mobile).
    # Sans ça, l'aperçu disait « rien à facturer » alors que l'import
    # les prenait.
    from sqlalchemy import or_ as _or_punch

    from app.models.bon_travail import BonTravail as _BonPunch

    _bt_ids = list(
        (
            await db.execute(
                select(_BonPunch.id).where(
                    _BonPunch.project_id == project_id
                )
            )
        ).scalars().all()
    )
    _punch_cond = Punch.project_id == project_id
    if _bt_ids:
        _punch_cond = _or_punch(
            _punch_cond, Punch.bon_travail_id.in_(_bt_ids)
        )
    punches = (
        await db.execute(
            select(Punch)
            .where(_punch_cond)
            .where(Punch.hours.is_not(None))
            .where(Punch.invoiced_at.is_(None))
            .where(Punch.approved.is_(True))
        )
    ).scalars().all()

    punch_buckets: List[BillablePunchBucket] = []
    total_hours = 0.0
    total_hours_projected = 0.0
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
        buckets: dict[tuple[int, float], dict] = {}
        for p in punches:
            emp = emps.get(p.employe_id)
            if emp and emp.billing_rate is not None:
                rate = float(emp.billing_rate)
            elif emp and emp.hourly_rate:
                rate = float(emp.hourly_rate)
            else:
                rate = 0.0
            key = (p.employe_id, rate)
            b = buckets.setdefault(
                key, {"hours": 0.0, "count": 0}
            )
            b["hours"] += float(p.hours or 0)
            b["count"] += 1
        for (emp_id, rate), b in buckets.items():
            emp = emps.get(emp_id)
            hours = b["hours"]
            projected = round(hours * rate, 2)
            total_hours += hours
            total_hours_projected += projected
            punch_buckets.append(
                BillablePunchBucket(
                    employe_id=emp_id,
                    employe_name=emp.full_name if emp else f"Employé #{emp_id}",
                    billing_rate=rate,
                    hours=round(hours, 2),
                    projected_amount=projected,
                    punch_count=b["count"],
                )
            )

    return BillablesSummary(
        achats=items,
        punch_buckets=punch_buckets,
        total_cost=round(total_cost, 2),
        total_projected=round(total_projected + total_hours_projected, 2),
        count=len(items) + len(punch_buckets),
        total_hours=round(total_hours, 2),
        total_hours_projected=round(total_hours_projected, 2),
    )
