"""
Project endpoints.

CRUD operations for projects with role-based access control.
"""

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUser, DBSession
from app.core.permissions import visible_project_ids
from app.schemas.project import (
    ProjectCreate,
    ProjectRead,
    ProjectReadWithClient,
    ProjectUpdate,
)
from app.services.project import ProjectService


router = APIRouter(prefix="/projects", tags=["projects"])


def _billing_kind(kind: Optional[str], pricing_kind: Optional[str]) -> str:
    """Type de facturation d'un projet d'après sa soumission liée :
    "contrat" (contrat APCHQ), sinon le pricing_kind ("forfaitaire" /
    "estime"). Détermine le défaut « refacturable » des achats."""
    if (kind or "") == "contract":
        return "contrat"
    return pricing_kind or "forfaitaire"


async def _responsible_name(db, user_id: Optional[int]) -> Optional[str]:
    """Nom d'affichage du responsable (sans dépendre du lazy-load async
    de la relation)."""
    if not user_id:
        return None
    from sqlalchemy import select as _select

    from app.models.user import User

    row = (
        await db.execute(
            _select(User.first_name, User.last_name, User.email).where(
                User.id == user_id
            )
        )
    ).first()
    if row is None:
        return None
    fn, ln, email = row
    name = " ".join(p for p in [fn, ln] if p).strip()
    return name or email


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project (admin only)",
)
async def create_project(
    data: ProjectCreate,
    db: DBSession,
    current_user: CurrentUser,
) -> ProjectRead:
    """Create a new project. Requires admin privileges."""
    service = ProjectService(db)
    project = await service.create(data)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client not found",
        )

    # Phase 5 — hook Drive Conventions (best-effort).
    try:
        from app.services.drive_conventions_hooks import on_entity_created

        await on_entity_created(
            entity_type="ConstructionProject",
            entity_id=project.id,
            user_id=current_user.id,
            db=db,
        )
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception(
            "drive hook 'created' a echoue pour ConstructionProject #%s "
            "(non bloquant)",
            project.id,
        )

    out = ProjectRead.model_validate(project)
    out.responsible_name = await _responsible_name(
        db, project.responsible_user_id
    )

    # Alerte commis comptable : sous-client QBO à convertir en Projet.
    try:
        from app.services.project_qbo_notify import notify_new_project_for_qbo

        await notify_new_project_for_qbo(db, project)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception(
            "alerte projet QBO non bloquante a échoué pour le projet #%s",
            project.id,
        )

    return out


@router.get(
    "",
    response_model=List[ProjectRead],
    summary="List all projects",
)
async def list_projects(
    db: DBSession,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    client_id: Optional[int] = Query(default=None, gt=0),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    kind: Optional[str] = Query(default=None),
) -> List[ProjectRead]:
    """List projects with optional client / status / kind filter.

    Sans `kind`, les bons de travail sont exclus (vue projets de
    construction propre). `kind=bon_travail` liste les ordres de travail.
    For employees (role=employee), only projects they've been assigned
    to via project_members are returned. Manager+ roles see everything.
    """
    service = ProjectService(db)
    visible = await visible_project_ids(db, current_user)
    projects = await service.list(
        skip=skip,
        limit=limit,
        client_id=client_id,
        status_filter=status_filter,
        kind=kind,
    )
    if visible is not None:
        projects = [p for p in projects if p.id in visible]

    # Enrichit chaque projet avec le total de sa soumission liée
    # (1 seule requête batch) — sert de fallback dans le kanban quand
    # `budget` est null mais qu'une soumission acceptée a un total.
    sm_ids = [p.soumission_id for p in projects if p.soumission_id]
    sm_totals: dict[int, Decimal] = {}
    sm_billing: dict[int, str] = {}
    if sm_ids:
        from sqlalchemy import select
        from app.models.soumission import Soumission

        rows = (
            await db.execute(
                select(
                    Soumission.id,
                    Soumission.total,
                    Soumission.kind,
                    Soumission.pricing_kind,
                ).where(Soumission.id.in_(set(sm_ids)))
            )
        ).all()
        for sid, total, kind, pricing_kind in rows:
            if total is not None:
                sm_totals[sid] = total
            sm_billing[sid] = _billing_kind(kind, pricing_kind)

    # Flux A — état de signature des bons liés (corrections) pour le badge
    # kanban : awaiting = bon envoyé non signé, signed = bon signé.
    proj_ids = [p.id for p in projects]
    awaiting_set: set = set()
    signed_set: set = set()
    if proj_ids:
        from sqlalchemy import select as _bsel
        from app.models.bon_travail import BonTravail

        brows = (
            await db.execute(
                _bsel(
                    BonTravail.project_id,
                    BonTravail.sent_at,
                    BonTravail.signed_at,
                ).where(BonTravail.project_id.in_(set(proj_ids)))
            )
        ).all()
        for pid, sent_at, signed_at in brows:
            if pid is None:
                continue
            if signed_at is not None:
                signed_set.add(pid)
            elif sent_at is not None:
                awaiting_set.add(pid)

    out: List[ProjectRead] = []
    for p in projects:
        d = ProjectRead.model_validate(p)
        if p.soumission_id and p.soumission_id in sm_totals:
            d.soumission_total = sm_totals[p.soumission_id]
        if p.soumission_id and p.soumission_id in sm_billing:
            d.billing_kind = sm_billing[p.soumission_id]
        d.awaiting_signature = p.id in awaiting_set
        d.has_signed_bon = p.id in signed_set
        out.append(d)
    return out


@router.get(
    "/{project_id}",
    response_model=ProjectReadWithClient,
    summary="Get a project by ID",
)
async def get_project(
    project_id: int,
    db: DBSession,
    current_user: CurrentUser,
) -> ProjectReadWithClient:
    """Get a project with its client. Employees must be members of
    the project; manager+ can access any project."""
    visible = await visible_project_ids(db, current_user)
    if visible is not None and project_id not in visible:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    service = ProjectService(db)
    project = await service.get_by_id(project_id, with_client=True)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    out = ProjectReadWithClient.model_validate(project)
    if project.soumission_id:
        from sqlalchemy import select
        from app.models.soumission import Soumission

        sm = (
            await db.execute(
                select(Soumission.kind, Soumission.pricing_kind).where(
                    Soumission.id == project.soumission_id
                )
            )
        ).first()
        if sm is not None:
            out.billing_kind = _billing_kind(sm[0], sm[1])
    out.responsible_name = await _responsible_name(
        db, project.responsible_user_id
    )
    return out


@router.put(
    "/{project_id}",
    response_model=ProjectRead,
    summary="Update a project (admin only)",
)
async def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: DBSession,
    current_user: CurrentUser,
) -> ProjectRead:
    """Update a project. Requires admin privileges."""
    service = ProjectService(db)
    # Statut AVANT mise à jour : on n'archive la soumission liée QUE sur la
    # TRANSITION vers « livré ». Sinon, sauvegarder un projet DÉJÀ livré
    # ré-archiverait une soumission qu'on aurait sortie à la main de la
    # colonne « Archivée » → la carte « changeait de colonne toute seule ».
    from sqlalchemy import select as _sel
    from app.models.project import Project as _Proj

    prev_status = (
        await db.execute(
            _sel(_Proj.status).where(_Proj.id == project_id)
        )
    ).scalar_one_or_none()
    project = await service.update(project_id, data)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or invalid client_id",
        )

    # Projet livré (= terminé) → on archive la soumission liée : elle
    # quitte la colonne « Acceptées » pour « Archivée » dans le tableau
    # des soumissions. Idempotent (ne réécrit pas si déjà archivée).
    #
    # IMPORTANT : c'est un effet SECONDAIRE. Il est isolé dans un savepoint
    # + try/except pour qu'un éventuel échec (ex. colonne Soumission
    # manquante en prod → SELECT qui plante) n'annule JAMAIS le passage du
    # projet en « livré ». Avant, un échec ici faisait rollback toute la
    # requête → le statut « revenait en cours » côté UI (régression vue sur
    # « 30 Quevillon »). On cible aussi des colonnes précises (pas SELECT *)
    # via un UPDATE direct, pour ne pas dépendre du reste du schéma.
    from app.models.project import ProjectStatus

    if (
        prev_status != ProjectStatus.DELIVERED.value
        and project.status == ProjectStatus.DELIVERED.value
        and project.soumission_id
    ):
        from app.services.project_auto_status import (
            archive_soumission_on_delivery,
        )

        await archive_soumission_on_delivery(db, project.id)

    out = ProjectRead.model_validate(project)
    out.responsible_name = await _responsible_name(
        db, project.responsible_user_id
    )
    return out


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project (admin only)",
)
async def delete_project(
    project_id: int,
    db: DBSession,
    current_user: CurrentUser,
) -> None:
    """Delete a project. Requires admin privileges."""
    service = ProjectService(db)
    deleted = await service.delete(project_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )


@router.post("/{project_id}/correction-bon")
async def create_correction_bon(
    project_id: int, db: DBSession, current_user: CurrentUser
) -> dict:
    """Crée un bon de CORRECTION / amélioration lié au projet (Flux A).

    Bon construction signable par le client : créé en brouillon ici, puis
    envoyé pour signature depuis sa fiche. Les coûts du retour de chantier
    s'accumulent sur le projet via project_id (visibilité du déficit)."""
    from datetime import datetime, timezone
    from sqlalchemy import select as _bsel

    from app.models.bon_travail import BonTravail
    from app.models.project import Project as _Proj

    proj = (
        await db.execute(_bsel(_Proj).where(_Proj.id == project_id))
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    bon = BonTravail(
        reference="BT-" + datetime.now(timezone.utc).strftime("%y%m%d-%H%M%S"),
        title="Correction / Amélioration",
        project_id=proj.id,
        client_id=proj.client_id,
        address=proj.address,
        status="draft",
        origin="correction",
        kind="construction",
        bon_type="temps_materiel",
        requires_signature=True,
    )
    db.add(bon)
    await db.flush()
    await db.commit()
    await db.refresh(bon)
    return {"bon_id": bon.id, "reference": bon.reference}


# ── Corrections / améliorations du projet (Flux A) ────────────────────────
class _CorrectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    title: str
    details: Optional[str]
    status: str
    position: int


class _CorrectionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    details: Optional[str] = None


class _CorrectionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    details: Optional[str] = None
    status: Optional[str] = None  # "a_faire" | "complete"


@router.get(
    "/{project_id}/corrections", response_model=List[_CorrectionRead]
)
async def list_corrections(
    project_id: int, db: DBSession, _: CurrentUser
) -> List[_CorrectionRead]:
    from sqlalchemy import select as _sel

    from app.models.project_correction import ProjectCorrection

    rows = (
        await db.execute(
            _sel(ProjectCorrection)
            .where(ProjectCorrection.project_id == project_id)
            .order_by(
                ProjectCorrection.position.asc(), ProjectCorrection.id.asc()
            )
        )
    ).scalars().all()
    return [_CorrectionRead.model_validate(r) for r in rows]


@router.post(
    "/{project_id}/corrections",
    response_model=_CorrectionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_correction(
    project_id: int,
    data: _CorrectionCreate,
    db: DBSession,
    _: CurrentUser,
) -> _CorrectionRead:
    from sqlalchemy import func, select as _sel

    from app.models.project_correction import ProjectCorrection

    pos = (
        await db.execute(
            _sel(func.count(ProjectCorrection.id)).where(
                ProjectCorrection.project_id == project_id
            )
        )
    ).scalar_one()
    obj = ProjectCorrection(
        project_id=project_id,
        title=data.title.strip(),
        details=(data.details or None),
        status="a_faire",
        position=int(pos or 0),
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return _CorrectionRead.model_validate(obj)


@router.patch(
    "/{project_id}/corrections/{correction_id}",
    response_model=_CorrectionRead,
)
async def update_correction(
    project_id: int,
    correction_id: int,
    data: _CorrectionUpdate,
    db: DBSession,
    _: CurrentUser,
) -> _CorrectionRead:
    from sqlalchemy import select as _sel

    from app.models.project_correction import ProjectCorrection

    obj = (
        await db.execute(
            _sel(ProjectCorrection).where(
                ProjectCorrection.id == correction_id,
                ProjectCorrection.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Correction not found")
    upd = data.model_dump(exclude_unset=True)
    if "title" in upd and upd["title"]:
        obj.title = upd["title"].strip()
    if "details" in upd:
        obj.details = upd["details"] or None
    if "status" in upd and upd["status"] in ("a_faire", "complete"):
        obj.status = upd["status"]
    await db.flush()
    await db.refresh(obj)
    return _CorrectionRead.model_validate(obj)


@router.delete(
    "/{project_id}/corrections/{correction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_correction(
    project_id: int,
    correction_id: int,
    db: DBSession,
    _: CurrentUser,
) -> None:
    from sqlalchemy import select as _sel

    from app.models.project_correction import ProjectCorrection

    obj = (
        await db.execute(
            _sel(ProjectCorrection).where(
                ProjectCorrection.id == correction_id,
                ProjectCorrection.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Correction not found")
    await db.delete(obj)
    await db.flush()
