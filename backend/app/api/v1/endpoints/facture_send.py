"""Send a facture to a client by email (PDF attached).
Also exposes GET /pdf for direct preview."""

import logging
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, DBSession
from app.core.essai import EffetExterneBloque
from app.models.user import User
from app.schemas.business import FactureRead
from app.services.facture_pdf import render_facture_pdf
from app.services.facture_send import (
    FactureBloqueeQB,
    FactureSendError,
    send_facture,
)
from app.services.permissions_service import require_capability


log = logging.getLogger(__name__)
router = APIRouter(prefix="/factures", tags=["factures"])


class FactureSendRequest(BaseModel):
    to: List[EmailStr] = Field(..., min_length=1)
    cc: Optional[List[EmailStr]] = None
    subject: Optional[str] = Field(default=None, max_length=255)
    message: Optional[str] = Field(default=None, max_length=4000)
    include_statement: bool = Field(
        default=False,
        description=(
            "Si True, joint en plus de la facture une page « État de "
            "compte » récapitulant toutes les factures et paiements "
            "du projet."
        ),
    )


@router.post(
    "/{facture_id}/send",
    response_model=FactureRead,
    summary="Send a facture to a client (PDF attached)",
)
async def send_facture_endpoint(
    facture_id: int,
    data: FactureSendRequest,
    db: DBSession,
    _: Annotated[User, Depends(require_capability("facture.send"))],
) -> FactureRead:
    """La facture passe par QuickBooks AVANT le courriel (services/
    facture_send.py). 409 si QuickBooks la refuse : rien n'est parti au
    client, la facture garde son statut et le motif est sur sa fiche."""
    try:
        fa = await send_facture(
            db,
            facture_id,
            to=[str(a) for a in data.to],
            cc=[str(a) for a in (data.cc or [])],
            subject=data.subject,
            message=data.message,
            include_statement=data.include_statement,
        )
    except FactureBloqueeQB as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    except FactureSendError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except (HTTPException, EffetExterneBloque):
        # Mode essai de l'aperçu : sa réponse 409 « rien n'est sorti »
        # vient du gestionnaire de l'application.
        raise
    except Exception as exc:  # noqa: BLE001
        # Jamais un « http_500 » muet à l'écran (Phil 2026-10-02) : le motif
        # réel (rendu PDF, numérotation, base) est journalisé ET renvoyé.
        log.exception("Envoi de la facture %s échoué", facture_id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Envoi échoué ({type(exc).__name__}) : {str(exc)[:300] or 'erreur interne'}",
        )

    # Plus de push QuickBooks après l'envoi : la facture y est entrée
    # juste avant le courriel, avec ses dates d'envoi.
    return FactureRead.model_validate(fa)


@router.get(
    "/{facture_id}/pdf",
    summary="Download the PDF preview of a facture",
)
async def get_facture_pdf(
    facture_id: int,
    db: DBSession,
    _: CurrentUser,
    include_statement: bool = False,
) -> Response:
    """Avec ``?include_statement=true``, l'état de compte du projet
    (toutes les factures + paiements) est appendé après la facture
    dans un PDF unique."""
    rendered = await render_facture_pdf(
        db, facture_id, include_statement=include_statement,
    )
    if rendered is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Facture not found")
    fa, pdf_bytes = rendered
    filename = (
        f"facture-{fa.reference}-avec-etat.pdf"
        if include_statement
        else f"facture-{fa.reference}.pdf"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
