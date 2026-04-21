"""Promote the prospect linked to a soumission into a Client.

Used when the auto-conversion on status=accepted didn't run (e.g.
status was set before the feature shipped, or the soumission was
not linked to a prospect at the time). Idempotent.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.client import Client
from app.models.contact_request import ContactRequest
from app.models.soumission import Soumission
from app.schemas.client import ClientRead


router = APIRouter(prefix="/soumissions", tags=["soumission-to-client"])


@router.post(
    "/{soumission_id}/convert-to-client",
    response_model=ClientRead,
    summary="Create or fetch a Client from the soumission's prospect",
)
async def convert_soumission_to_client(
    soumission_id: int,
    db: DBSession,
    _: CurrentUser,
) -> ClientRead:
    sm = (
        await db.execute(select(Soumission).where(Soumission.id == soumission_id))
    ).scalar_one_or_none()
    if sm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Soumission not found")

    # Reuse the existing client linked to the same prospect if any.
    if sm.contact_request_id:
        existing = (
            await db.execute(
                select(Client).where(Client.contact_request_id == sm.contact_request_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            if sm.client_id is None:
                sm.client_id = existing.id
                await db.flush()
            return ClientRead.model_validate(existing)

    # Or the client already linked directly on the soumission.
    if sm.client_id:
        linked = (
            await db.execute(select(Client).where(Client.id == sm.client_id))
        ).scalar_one_or_none()
        if linked is not None:
            return ClientRead.model_validate(linked)

    # Otherwise, create a new one from the prospect if we have one.
    if not sm.contact_request_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cette soumission n'est liée à aucun prospect ni client — "
                "crée le client manuellement depuis /app/clients."
            ),
        )

    cr = (
        await db.execute(
            select(ContactRequest).where(ContactRequest.id == sm.contact_request_id)
        )
    ).scalar_one_or_none()
    if cr is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Le prospect lié à cette soumission est introuvable.",
        )

    client = Client(
        name=cr.name,
        email=cr.email,
        phone=cr.phone,
        address=cr.address,
        contact_request_id=cr.id,
    )
    db.add(client)
    await db.flush()
    sm.client_id = client.id
    await db.flush()
    await db.refresh(client)
    return ClientRead.model_validate(client)
