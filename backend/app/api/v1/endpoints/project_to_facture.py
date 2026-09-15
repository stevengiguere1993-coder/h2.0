"""Create a Facture from a Project.

Pre-fills client, pulls the Project description, and optionally
seeds the line items from the project's approved (or all) punches —
grouped by employee × hourly_rate.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DBSession
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
from app.models.user import User
from app.schemas.business import FactureRead
from app.services.numbering import provisional_facture_reference
from app.services.permissions_service import require_capability


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
    apply_deposit_amount: Optional[float] = Field(
        default=None, ge=0,
        description=(
            "Acompte ($ HT) à déduire sur CETTE facture via une ligne "
            "négative « Moins acompte appliqué ». None (défaut) = "
            "calcul automatique au prorata de l'avancement facturé ; "
            "0 = ne rien appliquer cette fois. Toujours plafonné à "
            "l'acompte restant (reçu - déjà appliqué)."
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


@router.post(
    "/{project_id}/convert-to-facture",
    response_model=FactureRead,
    summary="Create a Facture from a Project (seeds line items from hours)",
)
async def convert_project_to_facture(
    project_id: int,
    data: ConvertToFactureRequest,
    db: DBSession,
    _: Annotated[User, Depends(require_capability("project.to_facture"))],
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
        # Référence PROVISOIRE : le vrai numéro est attribué à l'ENVOI
        # (pas de trous dans la séquence QuickBooks — audit).
        reference=provisional_facture_reference(),
        client_id=project.client_id,
        project_id=project.id,
        status=FactureStatus.DRAFT.value,
        # issued_at reste vide : la facture n'est « émise » qu'à l'envoi
        # au client, pas à sa création (cf. send_facture).
        due_at=due_at,
    )
    db.add(facture)
    await db.flush()

    # Projet lié à un BON DE TRAVAIL : la « demande de départ » (titre
    # du bon) coiffe chaque ligne importée, avec la sous-description
    # (« Main-d'œuvre », matériel…) en dessous — le client comprend
    # d'un coup d'œil à quelle demande la ligne se rattache.
    bon_demande: Optional[str] = None
    if (getattr(project, "kind", None) or "") == "bon_travail":
        from app.models.bon_travail import BonTravail as _BonDesc

        _bt = (
            await db.execute(
                select(_BonDesc)
                .where(_BonDesc.project_id == project.id)
                .order_by(_BonDesc.id)
            )
        ).scalars().first()
        if _bt is not None:
            bon_demande = (_bt.title or "").strip() or None

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
                    .where(
                        SoumissionItem.soumission_id == sm.id,
                        # Contrat courant : items retirés par avenant exclus.
                        SoumissionItem.retire_par_avenant_id.is_(None),
                    )
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
                            # Exclut les factures ANNULÉES du « déjà
                            # facturé » : une facture VOID ne représente
                            # plus un montant engagé (sinon sous-facturation
                            # ou blocage après annulation). On garde les
                            # brouillons (une étape en brouillon compte).
                            _Fac.status != FactureStatus.VOID.value,
                        )
                    )
                ).scalars().all()
                if prev_ids:
                    # L'ACOMPTE n'est plus compté comme de l'avancement
                    # (retour 2026-09-15) : c'est une AVANCE, déduite
                    # explicitement par une ligne « Moins acompte
                    # appliqué » — plus de répartition prorata invisible
                    # qui dérivait dès que le devis changeait. On exclut
                    # le nouveau kind « acompte », les lignes
                    # d'application, et les acomptes HISTORIQUES
                    # (lignes non liées dont le libellé commence par
                    # « Acompte »).
                    from sqlalchemy import and_ as _and, not_ as _not

                    _acompte_legacy = _and(
                        FactureItem.soumission_item_id.is_(None),
                        FactureItem.description.ilike("acompte%"),
                    )
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
                                FactureItem.kind.notin_(
                                    ("extra", "acompte", "acompte_applique")
                                ),
                                _not(_acompte_legacy),
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

            for it, delta_i in planned:
                item_total = float(it.total or 0)
                # Préfixe PAR LIGNE : la cible demandée (« 100% » = tout
                # le restant) était ambiguë seule — on précise entre
                # parenthèses la part de la TOTALITÉ du devis que CETTE
                # facture représente pour la ligne (ex. « 100% (39 % de
                # la totalité) — … »). Omise quand la ligne part au
                # complet en une seule facture (100 % = 100 %).
                line_pct = (
                    max(1, min(100, round(delta_i / item_total * 100)))
                    if item_total > 0
                    else 100
                )
                part = (
                    f" ({line_pct:g} % de la totalité)"
                    if line_pct != 100
                    else ""
                )
                if prefix_kind == "amount":
                    prefix = f"{int(round(prefix_value))} ${part} — "
                else:
                    prefix = (
                        f"{prefix_value:g}%{part} — "
                        if (pct != 100 or line_pct != 100)
                        else ""
                    )
                if abs(delta_i - item_total) <= 0.01 and float(it.quantity) > 0:
                    # Item chargé au complet → quantité/prix/unité d'origine.
                    qty = float(it.quantity)
                    unit = it.unit
                    unit_price = float(it.unit_price)
                    line_total = round(qty * unit_price, 2)
                else:
                    # Partiel → on CONSERVE le prix unitaire de la SOUMISSION
                    # (le client le retrouve tel quel sur le PDF) et on porte
                    # l'avancement sur la QUANTITÉ : quantité × prix unitaire
                    # = montant facturé sur CETTE facture. Le préfixe de
                    # description (« 85 % — … ») indique le % cumulatif
                    # atteint. Repli « lot » si le prix unitaire est nul
                    # (item de soumission sans prix ⇒ pas de quantité
                    # dérivable).
                    unit_price = float(it.unit_price)
                    if unit_price > 0:
                        unit = it.unit
                        # 6 décimales (précision de la colonne) : à 3,
                        # un gros prix unitaire dérivait de plusieurs
                        # dollars et dépassait le devis.
                        qty = round(delta_i / unit_price, 6)
                        line_total = round(qty * unit_price, 2)
                    else:
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

            # 3) ACOMPTE — application explicite (retour 2026-09-15).
            # L'acompte reçu est une AVANCE : on le déduit par une ligne
            # négative visible « Moins acompte appliqué », au prorata de
            # l'avancement que représente CETTE facture sur le restant du
            # contrat (la dernière facture applique tout le solde).
            # apply_deposit_amount : montant imposé ($ HT) ; 0 = sauter.
            if data.progressive_billing and delta_amount > 0:
                from sqlalchemy import and_ as _and2

                from app.models.facture import Facture as _FacAc

                _acompte_lignes = _and2(
                    FactureItem.soumission_item_id.is_(None),
                    FactureItem.description.ilike("acompte%"),
                    FactureItem.kind != "acompte_applique",
                )
                depot_recu = float(
                    (
                        await db.execute(
                            select(
                                func.coalesce(func.sum(FactureItem.total), 0)
                            )
                            .join(
                                _FacAc, _FacAc.id == FactureItem.facture_id
                            )
                            .where(
                                _FacAc.project_id == project_id,
                                _FacAc.id != facture.id,
                                _FacAc.status != FactureStatus.VOID.value,
                                (FactureItem.kind == "acompte")
                                | _acompte_lignes,
                            )
                        )
                    ).scalar_one()
                    or 0
                )
                depot_applique = -float(
                    (
                        await db.execute(
                            select(
                                func.coalesce(func.sum(FactureItem.total), 0)
                            )
                            .join(
                                _FacAc, _FacAc.id == FactureItem.facture_id
                            )
                            .where(
                                _FacAc.project_id == project_id,
                                _FacAc.status != FactureStatus.VOID.value,
                                FactureItem.kind == "acompte_applique",
                            )
                        )
                    ).scalar_one()
                    or 0
                )
                depot_restant = round(
                    max(0.0, depot_recu - depot_applique), 2
                )
                if depot_restant > 0.01 and (
                    data.apply_deposit_amount is None
                    or data.apply_deposit_amount > 0
                ):
                    # Restant du contrat AVANT cette facture (items
                    # actifs), pour le prorata.
                    restant_avant = round(
                        sum(
                            max(
                                0.0,
                                float(it.total or 0)
                                - (
                                    linked_billed.get(int(it.id), 0.0)
                                    + unattributed_billed
                                    * (
                                        float(it.total or 0) / sm_base
                                        if sm_base > 0
                                        else 0.0
                                    )
                                ),
                            )
                            for it in sm_items
                        ),
                        2,
                    )
                    if data.apply_deposit_amount is not None:
                        a_appliquer = float(data.apply_deposit_amount)
                    elif restant_avant > 0 and delta_amount < restant_avant - 0.01:
                        a_appliquer = round(
                            depot_restant * delta_amount / restant_avant, 2
                        )
                    else:
                        # Cette facture solde le contrat → tout le
                        # restant de l'acompte est appliqué.
                        a_appliquer = depot_restant
                    a_appliquer = round(
                        min(max(0.0, a_appliquer), depot_restant), 2
                    )
                    if a_appliquer > 0.01:
                        db.add(
                            FactureItem(
                                facture_id=facture.id,
                                position=pos,
                                description=(
                                    "Moins acompte appliqué — "
                                    f"{a_appliquer:.2f} $ de l'acompte "
                                    f"reçu de {depot_recu:.2f} $ "
                                    f"(restant après cette facture : "
                                    f"{depot_restant - a_appliquer:.2f} $)"
                                ),
                                unit="lot",
                                quantity=1,
                                unit_price=-a_appliquer,
                                total=-a_appliquer,
                                kind="acompte_applique",
                            )
                        )
                        pos += 1

    # 2) T&M — heures punchées approuvées (non encore facturées) au
    #    `billing_rate` de l'employé (fallback hourly_rate), groupées
    #    par (employé, taux). Marquage des punches après création.
    if data.include_hours:
        from sqlalchemy import or_ as _or_punch

        from app.models.bon_travail import BonTravail as _BonPunch

        # Heures du projet + heures pointées DIRECTEMENT sur un bon de
        # travail lié à ce projet (punch.bon_travail_id, sans project_id —
        # cas des bons internes pointés depuis le mobile). Sans ça, la
        # facture d'un bon n'importait aucune heure.
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
        stmt = select(Punch).where(_punch_cond)
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

            # Lignes « Main-d'œuvre » agrégées (AUCUN nom d'employé — le
            # client ne doit pas les voir), avec TAUX PLANCHER à l'import :
            #   - heures de PROJET : max(taux de facturation employé, 90 $/h)
            #   - heures liées à un BON DE TRAVAIL interne : 55 $/h
            # Deux lignes distinctes si les deux types coexistent (sinon le
            # 55 $ se noierait dans la moyenne). Prix unitaire = moyenne
            # pondérée du groupe ; tout reste modifiable sur la facture.
            from app.api.v1.endpoints.facture_import import (
                BON_HOURS_RATE,
                HOURS_RATE_FLOOR,
            )

            buckets: dict[str, list[float]] = {
                "projet": [0.0, 0.0],  # [heures, montant]
                "bon": [0.0, 0.0],
            }
            for p in punches:
                emp = emps.get(p.employe_id)
                if emp and emp.billing_rate is not None:
                    rate = float(emp.billing_rate)
                elif emp and emp.hourly_rate:
                    rate = float(emp.hourly_rate)
                else:
                    rate = 0.0
                if p.bon_travail_id:
                    rate = BON_HOURS_RATE
                    key = "bon"
                else:
                    rate = max(rate, HOURS_RATE_FLOOR)
                    key = "projet"
                h = float(p.hours or 0)
                buckets[key][0] += h
                buckets[key][1] += h * rate

            from datetime import datetime as _dt2, timezone as _tz2
            now_h = _dt2.now(_tz2.utc)
            items_by_key: dict[str, FactureItem] = {}
            for key, (b_hours, b_amount) in buckets.items():
                b_hours = round(b_hours, 2)
                b_amount = round(b_amount, 2)
                if b_hours <= 0:
                    continue
                if bon_demande:
                    desc_h = f"{bon_demande}\nMain-d'œuvre"
                elif key == "projet":
                    desc_h = "Main-d'œuvre"
                else:
                    desc_h = "Main-d'œuvre — bons de travail"
                item = FactureItem(
                    facture_id=facture.id,
                    position=pos,
                    description=desc_h,
                    unit="h",
                    quantity=b_hours,
                    unit_price=round(b_amount / b_hours, 2),
                    total=b_amount,
                    # Heures T&M = hors soumission de base → extra.
                    kind="extra",
                )
                db.add(item)
                items_by_key[key] = item
                pos += 1
            if items_by_key:
                await db.flush()
                for p in punches:
                    it = items_by_key.get(
                        "bon" if p.bon_travail_id else "projet"
                    )
                    if it is None:
                        continue  # groupe sans ligne (0 h) → punch libre
                    p.invoiced_at = now_h
                    p.facture_item_id = it.id

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
        # REGROUPEMENT : plusieurs achats au MÊME descriptif (accents/casse
        # ignorés) fusionnent en UNE ligne dont le montant additionne chaque
        # facture sélectionnée AVEC sa majoration. Les lignes horaires
        # (contrat flat_hourly) ne fusionnent jamais. Chaque achat garde son
        # lien retour (facture_item_id) pour la dé-refacturation.
        from app.api.v1.endpoints.facture_import import (
            _merge_label_key,
            achat_line_prefix,
        )

        merged: dict[str, FactureItem] = {}
        for ac in achats:
            billed, _rule_label = _compute_billed_amount(
                ac, data.achat_markup_overrides, contracts_by_st
            )
            base_desc = ac.description or f"Achat {ac.reference or ac.id}"
            line_prefix = achat_line_prefix(ac.kind)
            # La majoration / règle de facturation (`rule_label`) est
            # INTERNE : on l'applique au montant (`billed`) mais on ne
            # l'affiche JAMAIS dans la description vue par le client.
            label = f"{line_prefix} — {base_desc}"
            if bon_demande:
                # Facture d'un bon : la demande de départ coiffe la
                # sous-description matériel/sous-traitance.
                label = f"{bon_demande}\n{label}"
            contract = (
                contracts_by_st.get(ac.sous_traitant_id or 0)
                if ac.kind == "sub_invoice"
                else None
            )
            is_hourly = bool(
                contract is not None
                and contract.billing_mode == "flat_hourly"
            )
            if not is_hourly:
                existing = merged.get(_merge_label_key(label))
                if existing is not None:
                    existing.total = round(
                        float(existing.total) + billed, 2
                    )
                    existing.unit_price = existing.total
                    new_items.append((ac, existing))
                    continue
            if is_hourly:
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
                description=label,
                unit=unit,
                quantity=qty,
                unit_price=up,
                total=billed,
                # Achats / matériel / sous-traitant = hors soumission de
                # base → extra (ne compte pas dans la cible cumulative).
                kind="extra",
            )
            db.add(item)
            if not is_hourly:
                merged[_merge_label_key(label)] = item
            new_items.append((ac, item))
            pos += 1

        await db.flush()
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc)
        for ac, item in new_items:
            ac.invoiced_at = now
            ac.facture_item_id = item.id
        # Dépense QB liée → flip CIBLÉ de la case FACTURABLE (NotBillable)
        # en fond : l'imputation de dépense facturable en attente disparaît
        # (la refacturation majorée est déjà sur la facture Kratos). Ciblé
        # = fonctionne aussi pour les achats importés de QB, sans doublon.
        import asyncio as _asyncio

        from app.services.achat_qbo import flip_qbo_billable_now

        for ac, _item in new_items:
            if ac.qbo_bill_id or ac.qbo_purchase_id:
                _asyncio.create_task(
                    flip_qbo_billable_now(int(ac.id), False)
                )

    await db.flush()
    # Recompute totaux facture depuis les items qu'on vient de créer
    # (subtotal / tps / tvq / total). Sans ça, Facture.total reste à
    # NULL → KPI projet « Facturé » affiche 0 $ même après création.
    from app.api.v1.endpoints.facture_items import _recompute_facture_totals

    await _recompute_facture_totals(db, facture.id)

    # Facture créée depuis un BON DE TRAVAIL : le bon « complété — à
    # refacturer » passe à « facturé » — sa carte change de colonne
    # toute seule sur le kanban (même règle que l'import multi-bons).
    if (getattr(project, "kind", None) or "") == "bon_travail":
        from app.models.bon_travail import (
            BonTravail as _BonSt,
            BonTravailStatus as _BSt,
        )

        for _b in (
            await db.execute(
                select(_BonSt).where(
                    _BonSt.project_id == project.id,
                    _BonSt.status == _BSt.COMPLETE_A_REFACTURER.value,
                )
            )
        ).scalars():
            _b.status = _BSt.FACTURE.value
        await db.flush()

    await db.refresh(facture)
    return FactureRead.model_validate(facture)


# ─────────────────────── État du contrat (retour 2026-09-15) ──────────
# Vue d'ensemble de la facturation progressive d'un projet à contrat :
# contrat de base + avenants = contrat courant, facturé à date (extras
# et acomptes exclus), acompte reçu / appliqué / restant, solde à
# facturer et % réel — global et ligne par ligne. C'est la source que
# l'encadré « État du contrat » de la fiche facture/projet affiche.


class EtatContratLigne(BaseModel):
    item_id: int
    description: str
    au_contrat: float
    facture: float
    restant: float
    pct: float
    retire: bool = False
    avenant: Optional[str] = None


class EtatContrat(BaseModel):
    soumission_id: int
    soumission_reference: str
    contrat_base: float
    avenants_impact: float
    contrat_courant: float
    facture_a_date: float
    extras_factures: float
    acompte_recu: float
    acompte_applique: float
    acompte_restant: float
    solde_a_facturer: float
    pct_avancement: float
    #: Items facturés AU-DELÀ de leur montant au contrat (crédit à
    #: prévoir) — libellés lisibles.
    surfactures: list[str] = []
    lignes: list[EtatContratLigne] = []


@router.get(
    "/{project_id}/etat-contrat",
    response_model=EtatContrat,
    summary="État de la facturation progressive du contrat (avenants, "
    "acompte, facturé à date, solde)",
)
async def etat_contrat(
    project_id: int, db: DBSession, _: Annotated[User, Depends(require_capability("project.to_facture"))]
) -> EtatContrat:
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None or not project.soumission_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Projet sans soumission liée — pas de contrat à suivre.",
        )
    sm = await db.get(Soumission, project.soumission_id)
    if sm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Soumission introuvable.")

    items = (
        await db.execute(
            select(SoumissionItem)
            .where(SoumissionItem.soumission_id == sm.id)
            .order_by(SoumissionItem.position.asc(), SoumissionItem.id.asc())
        )
    ).scalars().all()
    actifs = [it for it in items if it.retire_par_avenant_id is None]
    contrat_courant = round(sum(float(it.total or 0) for it in actifs), 2)

    from app.models.soumission_avenant import SoumissionAvenant

    avenants = (
        await db.execute(
            select(SoumissionAvenant)
            .where(SoumissionAvenant.soumission_id == sm.id)
            .order_by(SoumissionAvenant.numero.asc())
        )
    ).scalars().all()
    avenants_impact = round(
        sum(float(a.impact_subtotal or 0) for a in avenants), 2
    )
    av_ref = {a.id: a.reference for a in avenants}
    contrat_base = round(contrat_courant - avenants_impact, 2)

    fac_ids = (
        await db.execute(
            select(Facture.id).where(
                Facture.project_id == project_id,
                Facture.status != FactureStatus.VOID.value,
            )
        )
    ).scalars().all()

    facture_par_item: dict[int, float] = {}
    extras = 0.0
    acompte_recu = 0.0
    acompte_applique = 0.0
    non_attribue = 0.0
    if fac_ids:
        rows = (
            await db.execute(
                select(
                    FactureItem.soumission_item_id,
                    FactureItem.kind,
                    FactureItem.description,
                    func.coalesce(func.sum(FactureItem.total), 0),
                )
                .where(FactureItem.facture_id.in_(fac_ids))
                .group_by(
                    FactureItem.soumission_item_id,
                    FactureItem.kind,
                    FactureItem.description,
                )
            )
        ).all()
        for sid, kind, desc, tot in rows:
            m = round(float(tot or 0), 2)
            k = kind or "service"
            if k == "acompte_applique":
                acompte_applique += -m
            elif k == "acompte" or (
                sid is None and (desc or "").lower().startswith("acompte")
            ):
                acompte_recu += m
            elif k == "extra":
                extras += m
            elif sid is not None:
                facture_par_item[int(sid)] = (
                    facture_par_item.get(int(sid), 0.0) + m
                )
            else:
                non_attribue += m

    facture_a_date = round(
        sum(facture_par_item.values()) + non_attribue, 2
    )
    acompte_recu = round(acompte_recu, 2)
    acompte_applique = round(acompte_applique, 2)
    acompte_restant = round(max(0.0, acompte_recu - acompte_applique), 2)

    lignes: list[EtatContratLigne] = []
    surfactures: list[str] = []
    for it in items:
        au_contrat = (
            0.0
            if it.retire_par_avenant_id is not None
            else round(float(it.total or 0), 2)
        )
        # Le « non attribué » (anciennes factures sans lien par item) est
        # réparti au prorata du poids de la ligne — même règle que la
        # facturation progressive, pour que les deux affichent pareil.
        share = (
            (float(it.total or 0) / contrat_courant)
            if contrat_courant > 0 and it.retire_par_avenant_id is None
            else 0.0
        )
        b = round(
            facture_par_item.get(int(it.id), 0.0) + non_attribue * share, 2
        )
        if b <= 0.005 and it.retire_par_avenant_id is not None:
            # Ligne retirée jamais facturée : pas de bruit dans l'état.
            continue
        restant = round(max(0.0, au_contrat - b), 2)
        pct = round((b / au_contrat * 100) if au_contrat > 0 else 100.0, 1)
        av = (
            av_ref.get(it.retire_par_avenant_id)
            if it.retire_par_avenant_id
            else av_ref.get(it.avenant_id) if it.avenant_id else None
        )
        lignes.append(
            EtatContratLigne(
                item_id=it.id,
                description=it.description,
                au_contrat=au_contrat,
                facture=b,
                restant=restant,
                pct=min(pct, 999.9),
                retire=it.retire_par_avenant_id is not None,
                avenant=av,
            )
        )
        if b - au_contrat > 0.01:
            surfactures.append(
                f"« {it.description[:80]} » : {b:.2f} $ facturé pour "
                f"{au_contrat:.2f} $ au contrat."
            )

    return EtatContrat(
        soumission_id=sm.id,
        soumission_reference=sm.reference,
        contrat_base=contrat_base,
        avenants_impact=avenants_impact,
        contrat_courant=contrat_courant,
        facture_a_date=facture_a_date,
        extras_factures=round(extras, 2),
        acompte_recu=acompte_recu,
        acompte_applique=acompte_applique,
        acompte_restant=acompte_restant,
        solde_a_facturer=round(
            max(0.0, contrat_courant - facture_a_date), 2
        ),
        pct_avancement=round(
            (facture_a_date / contrat_courant * 100)
            if contrat_courant > 0
            else 0.0,
            1,
        ),
        surfactures=surfactures,
        lignes=lignes,
    )
