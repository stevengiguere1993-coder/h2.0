"""Change the status of a soumission and propagate to the linked prospect.

PATCH /api/v1/soumissions/{soumission_id}/status
Body: { "status": "accepted" | "rejected" | "expired" | "draft" | "sent" }

Propagation rules (only when the prospect isn't already in a terminal
state):
    soumission.sent     -> prospect.quoted
    soumission.accepted -> prospect.won
    soumission.rejected -> prospect.lost
    soumission.expired  -> prospect.lost
"""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.client import Client
from app.models.contact_request import ContactRequest, ContactRequestStatus
from app.models.soumission import Soumission, SoumissionStatus
from app.schemas.business import SoumissionRead


router = APIRouter(prefix="/soumissions", tags=["soumission-status"])


SoumissionStatusLiteral = Literal[
    "draft", "sent", "accepted", "rejected", "expired", "spam"
]


class StatusChangeRequest(BaseModel):
    status: SoumissionStatusLiteral


_SOUMISSION_TO_CRM = {
    SoumissionStatus.SENT.value: ContactRequestStatus.QUOTED.value,
    SoumissionStatus.ACCEPTED.value: ContactRequestStatus.WON.value,
    SoumissionStatus.REJECTED.value: ContactRequestStatus.LOST.value,
    SoumissionStatus.EXPIRED.value: ContactRequestStatus.LOST.value,
    # Soumission « spam » → le prospect lié est classé Refusé/Perdu.
    SoumissionStatus.SPAM.value: ContactRequestStatus.LOST.value,
}


@router.patch(
    "/{soumission_id}/status",
    response_model=SoumissionRead,
    summary="Change soumission status and propagate to the prospect CRM",
)
async def change_soumission_status(
    soumission_id: int,
    data: StatusChangeRequest,
    db: DBSession,
    _: CurrentUser,
) -> SoumissionRead:
    sm = (
        await db.execute(select(Soumission).where(Soumission.id == soumission_id))
    ).scalar_one_or_none()
    if sm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Soumission not found")

    now = datetime.now(timezone.utc)
    sm.status = data.status
    if data.status == SoumissionStatus.SENT.value and sm.sent_at is None:
        sm.sent_at = now
    if data.status == SoumissionStatus.ACCEPTED.value and sm.accepted_at is None:
        sm.accepted_at = now

    # Propagate the soumission status onto the linked prospect every
    # time — including corrections (e.g. the user clicked "accepted"
    # by mistake and reverts to "sent"). We deliberately don't make
    # won/lost sticky because a mis-click should be reversible from
    # the soumission side.
    target = _SOUMISSION_TO_CRM.get(data.status)
    # "draft" is intentionally absent from the map: putting a
    # soumission back to draft leaves the prospect untouched (the
    # staff can decide separately where the prospect sits).
    cr: ContactRequest | None = None
    if target and sm.contact_request_id:
        cr = (
            await db.execute(
                select(ContactRequest).where(
                    ContactRequest.id == sm.contact_request_id
                )
            )
        ).scalar_one_or_none()
        if cr is not None:
            cr.status = target

    # When the soumission becomes "accepted", promote the prospect
    # into the Client roster (idempotent — we reuse any existing
    # Client that already points at this contact_request).
    if data.status == SoumissionStatus.ACCEPTED.value and cr is not None:
        existing_client = (
            await db.execute(
                select(Client).where(Client.contact_request_id == cr.id)
            )
        ).scalar_one_or_none()
        if existing_client is None:
            client = Client(
                name=cr.name,
                email=cr.email,
                phone=cr.phone,
                address=cr.address,
                contact_request_id=cr.id,
            )
            db.add(client)
            await db.flush()
            # Link the soumission to the freshly-created client so
            # downstream factures / projets pick it up automatically.
            if sm.client_id is None:
                sm.client_id = client.id
        else:
            if sm.client_id is None:
                sm.client_id = existing_client.id

    await db.flush()

    # Auto-création du projet + facture d'acompte DRAFT à
    # l'acceptation. Idempotent : si déjà créé (ex. via la signature
    # publique antérieure ou un changement de statut précédent), la
    # fonction le détecte et ne refait rien. La facture reste en
    # DRAFT — l'utilisateur clique « Envoyer au client » quand il
    # est prêt.
    if data.status == SoumissionStatus.ACCEPTED.value:
        from app.api.v1.endpoints.soumission_to_project import (
            provision_project_for_soumission,
        )
        try:
            await provision_project_for_soumission(db, sm, notify_qbo=True)
            await db.flush()
        except Exception:  # noqa: BLE001
            # Best-effort : si la provision échoue (DB transient,
            # données partielles…), on ne bloque pas le changement
            # de statut. L'utilisateur pourra relancer manuellement
            # via /soumissions/{id}/convert-to-project.
            pass

    await db.refresh(sm)
    return SoumissionRead.model_validate(sm)
