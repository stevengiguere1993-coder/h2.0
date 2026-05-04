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

The core logic is exposed via :func:`provision_project_for_soumission`
so that automatic acceptance flows (status change, public client
signature) can reuse it without going through this HTTP handler.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DBSession
from app.models.contact_request import ContactRequest
from app.models.facture import Facture, FactureStatus
from app.models.facture_item import FactureItem
from app.models.project import Project, ProjectStatus
from app.models.soumission import Soumission
from app.models.soumission_item import SoumissionItem
from app.schemas.project import ProjectRead
from app.services.numbering import next_facture_number


router = APIRouter(prefix="/soumissions", tags=["soumission-to-project"])

TPS_RATE = 0.05
TVQ_RATE = 0.09975

#: Pourcentage par défaut de la facture d'acompte créée à
#: l'acceptation d'une soumission.
DEFAULT_DEPOSIT_PERCENTAGE = 25


class ConvertToProjectRequest(BaseModel):
    deposit_percentage: int = Field(
        default=DEFAULT_DEPOSIT_PERCENTAGE, ge=0, le=100,
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


async def _soumission_subtotal(db: AsyncSession, sm: Soumission) -> float:
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


async def provision_project_for_soumission(
    db: AsyncSession,
    sm: Soumission,
    *,
    deposit_percentage: int = DEFAULT_DEPOSIT_PERCENTAGE,
    due_in_days: int = 0,
) -> Tuple[Project, Optional[Facture]]:
    """Create the Project (+ optional deposit Facture in DRAFT) for an
    accepted Soumission. Idempotent : si un projet existe déjà pour
    cette soumission, on le retourne tel quel sans recréer la facture.

    La facture d'acompte est créée en **DRAFT** : elle apparaît dans
    /facturation mais n'est PAS envoyée tant que l'utilisateur ne
    clique pas explicitement sur « Envoyer au client ».

    Le caller doit gérer le `await db.flush()` / `db.commit()` final
    selon son contexte.
    """
    existing = (
        await db.execute(
            select(Project).where(Project.soumission_id == sm.id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, None
    # Si l'utilisateur a explicitement supprimé le projet rattaché à
    # cette soumission, on ne le re-provisionne PAS — sinon il
    # ressuscite à chaque appel.
    if getattr(sm, "project_skip_backfill", False):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "Le projet rattaché à cette soumission a été supprimé "
                "volontairement. Pour le recréer, repasse par /facturation."
            ),
        )

    contact: Optional[ContactRequest] = None
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

    facture: Optional[Facture] = None
    if deposit_percentage > 0:
        sm_subtotal = await _soumission_subtotal(db, sm)
        if sm_subtotal > 0:
            ratio = deposit_percentage / 100.0
            deposit_subtotal = round(sm_subtotal * ratio, 2)
            tps = round(deposit_subtotal * TPS_RATE, 2)
            tvq = round(deposit_subtotal * TVQ_RATE, 2)
            grand_total = round(deposit_subtotal + tps + tvq, 2)

            facture = Facture(
                reference=await next_facture_number(db),
                client_id=project.client_id,
                project_id=project.id,
                status=FactureStatus.DRAFT.value,
                issued_at=datetime.now(timezone.utc),
                due_at=(
                    datetime.now(timezone.utc)
                    + timedelta(days=due_in_days)
                ),
                subtotal=deposit_subtotal,
                tps=tps,
                tvq=tvq,
                total=grand_total,
                balance=grand_total,
                client_note=(
                    f"Acompte de {deposit_percentage} % sur la soumission "
                    f"{sm.reference}. Le solde sera facturé selon "
                    "l'avancement des travaux."
                ),
            )
            db.add(facture)
            await db.flush()
            db.add(
                FactureItem(
                    facture_id=facture.id,
                    position=0,
                    description=(
                        f"Acompte {deposit_percentage} % — Soumission "
                        f"{sm.reference}"
                        + (f" — {sm.title}" if sm.title else "")
                    ),
                    unit="lot",
                    quantity=1,
                    unit_price=deposit_subtotal,
                    total=deposit_subtotal,
                )
            )
            await db.flush()

    return project, facture


async def backfill_accepted_soumissions(db: AsyncSession) -> int:
    """Crée le projet (et la facture d'acompte DRAFT) pour toutes les
    soumissions déjà acceptées qui n'ont pas encore de projet associé.

    Idempotent : appelable plusieurs fois, ne refait rien sur les
    soumissions déjà rattachées à un projet.

    Conçu pour être appelé au démarrage de l'app, après init_db, pour
    rattraper les soumissions acceptées avant l'introduction de
    l'auto-création (PR #45).

    Retourne le nombre de projets créés.
    """
    from app.models.soumission import SoumissionStatus

    # Soumissions ACCEPTED sans Project lié (LEFT JOIN puis filtre).
    # IMPORTANT : on exclut les soumissions dont le projet a été
    # supprimé volontairement (project_skip_backfill=True). Sans ça,
    # le projet ressuscite à chaque démarrage du serveur.
    rows = (
        await db.execute(
            select(Soumission)
            .outerjoin(Project, Project.soumission_id == Soumission.id)
            .where(
                Soumission.status == SoumissionStatus.ACCEPTED.value,
                Project.id.is_(None),
                Soumission.project_skip_backfill.is_(False),
            )
        )
    ).scalars().all()

    created = 0
    for sm in rows:
        try:
            project, _facture = await provision_project_for_soumission(db, sm)
            # provision_project_for_soumission est idempotente — si elle
            # retourne un projet existant elle ne crée rien et renvoie
            # facture=None. On compte uniquement les vraies créations.
            if project is not None and project.soumission_id == sm.id:
                created += 1
        except Exception:  # noqa: BLE001
            # Best-effort : un échec sur une soumission ne bloque pas
            # le rattrapage des autres.
            continue
    if created > 0:
        await db.commit()
    return created


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

    cfg = body or ConvertToProjectRequest()
    project, _facture = await provision_project_for_soumission(
        db, sm,
        deposit_percentage=cfg.deposit_percentage,
        due_in_days=cfg.due_in_days,
    )
    return ProjectRead.model_validate(project)
