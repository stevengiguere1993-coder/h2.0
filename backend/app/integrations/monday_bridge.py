"""
Transitional bridge: push incoming contact-form submissions into the
existing Monday.com CRM Soumissions board so the team can keep working
from Monday while the internal portal is being built.

Failures are logged and swallowed: they must never break the public
contact endpoint.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from app.core.config import settings
from app.models.contact_request import ContactRequest

log = logging.getLogger(__name__)

MONDAY_URL = "https://api.monday.com/v2"
API_VERSION = "2024-10"


def _build_item_name(r: ContactRequest) -> str:
    pt = (r.project_type or "autre").replace("_", " ").title()
    return f"{r.name} - {pt}"[:250]


def _build_update_body(r: ContactRequest, reference: str) -> str:
    lines = [
        f"Nouvelle demande de contact (reference {reference})",
        "",
        f"Nom: {r.name}",
        f"Courriel: {r.email}",
        f"Telephone: {r.phone or '-'}",
        f"Adresse du projet: {r.address or '-'}",
        f"Type de projet: {r.project_type}",
        f"Budget: {r.budget_range or '-'}",
        f"Langue: {r.locale}",
        f"Source: {r.source or 'site-web'}",
        f"Consentement marketing: {'oui' if r.marketing_consent else 'non'}",
        "",
        "Message:",
        r.message or "(aucun)",
    ]
    return "\n".join(lines)


async def push_contact_to_monday(
    record: ContactRequest, reference: str, board_id: Optional[int] = None
) -> Optional[str]:
    """Create a Monday item for a ContactRequest.

    Returns the new Monday item id on success, or None if disabled or failing.
    Never raises.
    """
    token = settings.monday_api_token
    target_board = board_id or settings.monday_crm_board_id
    if not token or not target_board:
        log.info("Monday bridge disabled: no token or board id configured")
        return None

    item_name = _build_item_name(record)
    update_body = _build_update_body(record, reference)

    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "API-Version": API_VERSION,
    }

    create_mutation = (
        "mutation ($boardId: ID!, $itemName: String!) { "
        "create_item(board_id: $boardId, item_name: $itemName) { id } }"
    )
    update_mutation = (
        "mutation ($itemId: ID!, $body: String!) { "
        "create_update(item_id: $itemId, body: $body) { id } }"
    )

    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            r = await client.post(
                MONDAY_URL,
                json={
                    "query": create_mutation,
                    "variables": {
                        "boardId": str(target_board),
                        "itemName": item_name,
                    },
                },
            )
            data = r.json()
            if "errors" in data:
                log.warning("Monday create_item errors: %s", data["errors"])
                return None
            item_id = (data.get("data", {}).get("create_item") or {}).get("id")
            if not item_id:
                log.warning("Monday create_item returned no id: %s", data)
                return None

            # Attach all the form details as the first update (comment).
            r2 = await client.post(
                MONDAY_URL,
                json={
                    "query": update_mutation,
                    "variables": {
                        "itemId": str(item_id),
                        "body": update_body,
                    },
                },
            )
            data2 = r2.json()
            if "errors" in data2:
                log.warning(
                    "Monday create_update errors on item %s: %s",
                    item_id, data2["errors"],
                )

            log.info("Pushed ContactRequest %s to Monday item %s", record.id, item_id)
            return str(item_id)
    except httpx.HTTPError as exc:
        log.warning("Monday bridge HTTP error: %s", exc)
        return None
    except json.JSONDecodeError as exc:
        log.warning("Monday bridge JSON decode error: %s", exc)
        return None
    except Exception as exc:  # pragma: no cover - belt and suspenders
        log.exception("Monday bridge unexpected error: %s", exc)
        return None
