"""Convert an accepted soumission into a Project.

Creates a new Project linked back to the Soumission + ContactRequest,
pre-filling name / address / budget from the soumission context.
Idempotent when a project already exists for that soumission: the
existing one is returned unchanged.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.contact_request import ContactRequest
from app.models.project import Project, ProjectStatus
from app.models.soumission import Soumission
from app.schemas.project import ProjectRead


router = APIRouter(prefix="/soumissions", tags=["soumission-to-project"])


@router.post(
    "/{soumission_id}/convert-to-project",
    response_model=ProjectRead,
    summary="Create or fetch a project from a soumission",
)
async def convert_soumission_to_project(
    soumission_id: int,
    db: DBSession,
    _: CurrentUser,
) -> ProjectRead:
    sm = (
        await db.execute(select(Soumission).where(Soumission.id == soumission_id))
    ).scalar_one_or_none()
    if sm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Soumission not found")

    # Idempotent: if a project already points at this soumission, return it.
    existing = (
        await db.execute(
            select(Project).where(Project.soumission_id == soumission_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return ProjectRead.model_validate(existing)

    # Pull contact info (address / name) from the linked prospect.
    contact: ContactRequest | None = None
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
    return ProjectRead.model_validate(project)
