"""Push a Client to QuickBooks Online as a Customer.

    POST /api/v1/clients/{id}/push-to-qbo

Uses the existing QuickBooksClient.ensure_customer helper — idempotent
by design: if a QBO Customer with the same email or DisplayName already
exists it is reused instead of creating a duplicate. The returned
Customer.Id is persisted back on the Client row so subsequent calls
are cheap (no QBO query) and the UI can show a « QB ✓ » badge.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DBSession, RequireManager
from app.integrations.quickbooks import QuickBooksError, get_qbo
from app.models.client import Client


log = logging.getLogger(__name__)

router = APIRouter(prefix="/clients", tags=["clients-qbo"])


def _format_phone(raw: Optional[str]) -> Optional[str]:
    """Normalise vers (XXX) XXX-XXXX avant de pousser à QBO, comme
    partout ailleurs dans l'app. Renvoie la valeur brute pour les
    formats étrangers ou incomplets."""
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return raw
    return f"({digits[0:3]}) {digits[3:6]}-{digits[6:]}"


class PushToQboResponse(BaseModel):
    ok: bool
    client_id: int
    qbo_customer_id: str
    display_name: str
    created: bool  # True si on a créé, False si on a réutilisé un existant


@router.post(
    "/{client_id}/push-to-qbo",
    response_model=PushToQboResponse,
    summary="Créer (ou réutiliser) le Customer QBO pour ce client",
)
async def push_client_to_qbo(
    client_id: int,
    db: DBSession,
    _: RequireManager,
) -> PushToQboResponse:
    client = (
        await db.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Client introuvable."
        )

    qbo = get_qbo()
    # On force un chargement DB pour récupérer realm_id + refresh_token
    # posés par /qbo/callback — sinon la première exécution après un
    # reboot tape sur l'env qui peut être vide.
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "QuickBooks n'est pas connecté. Connecte une compagnie "
            "depuis /app/parametres.",
        )

    # Si déjà synchronisé, court-circuit : on retourne l'id courant
    # sans appeler QBO. Ça évite de payer un round-trip quand l'utilisateur
    # reclique par erreur.
    was_linked: Optional[str] = client.qbo_customer_id

    try:
        customer = await qbo.ensure_customer(
            display_name=client.name,
            email=client.email,
            phone=_format_phone(client.phone),
            billing_address=client.address,
        )
    except QuickBooksError as exc:
        log.warning("QBO push-to-qbo failed for client %s: %s", client_id, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"QuickBooks a refusé la requête : {exc}",
        )
    except Exception as exc:
        log.exception("QBO push-to-qbo crashed for client %s", client_id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Erreur interne lors du push QBO : {exc}",
        )

    qbo_id = str(customer.get("Id") or "")
    if not qbo_id:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "QuickBooks n'a pas retourné d'ID pour le Customer créé.",
        )

    # On considère "created" vrai si on vient de découvrir l'id pour
    # la 1re fois côté portail. Le helper ensure_customer peut avoir
    # trouvé un existant mais c'est la 1re fois qu'on le lie ici.
    client.qbo_customer_id = qbo_id
    await db.flush()

    return PushToQboResponse(
        ok=True,
        client_id=client.id,
        qbo_customer_id=qbo_id,
        display_name=str(customer.get("DisplayName") or client.name),
        created=(was_linked != qbo_id),
    )
