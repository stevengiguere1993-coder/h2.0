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
from typing import Iterable, List, Optional, Tuple

import httpx

from app.core.config import settings
from app.models.contact_request import ContactRequest

log = logging.getLogger(__name__)

MONDAY_URL = "https://api.monday.com/v2"
MONDAY_FILE_URL = "https://api.monday.com/v2/file"
API_VERSION = "2024-10"

# (filename, bytes, content_type)
PhotoPayload = Tuple[str, bytes, str]

_photos_column_cache: dict[int, str] = {}


def _build_item_name(r: ContactRequest) -> str:
    pt = (r.project_type or "autre").replace("_", " ").title()
    return f"{r.name} - {pt}"[:250]


def _build_update_body(r: ContactRequest, reference: str, photo_count: int) -> str:
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
        f"Photos jointes: {photo_count}",
        "",
        "Message:",
        r.message or "(aucun)",
    ]
    return "\n".join(lines)


async def _ensure_photos_column(
    client: httpx.AsyncClient, board_id: int
) -> Optional[str]:
    """Return the id of a file-type column on board_id, creating one if missing."""
    cached = _photos_column_cache.get(board_id)
    if cached:
        return cached

    # 1. Look for an existing file column, prefer titles containing "photo".
    list_q = (
        "query ($boardId: [ID!]!) { boards(ids: $boardId) { "
        "columns { id title type } } }"
    )
    try:
        r = await client.post(
            MONDAY_URL,
            json={"query": list_q, "variables": {"boardId": [str(board_id)]}},
        )
        data = r.json()
        boards = data.get("data", {}).get("boards") or []
        columns = boards[0].get("columns", []) if boards else []
    except Exception as exc:
        log.warning("Could not list Monday columns on board %s: %s", board_id, exc)
        return None

    file_cols = [c for c in columns if c.get("type") == "file"]
    preferred = [c for c in file_cols if "photo" in (c.get("title") or "").lower()]
    chosen = (preferred or file_cols or [None])[0]
    if chosen and chosen.get("id"):
        _photos_column_cache[board_id] = chosen["id"]
        return chosen["id"]

    # 2. Create a new Photos column.
    create_q = (
        "mutation ($boardId: ID!, $title: String!) { "
        "create_column(board_id: $boardId, title: $title, column_type: file) "
        "{ id } }"
    )
    try:
        r = await client.post(
            MONDAY_URL,
            json={
                "query": create_q,
                "variables": {"boardId": str(board_id), "title": "Photos"},
            },
        )
        data = r.json()
        if "errors" in data:
            log.warning("Monday create_column errors: %s", data["errors"])
            return None
        new_id = (data.get("data", {}).get("create_column") or {}).get("id")
        if new_id:
            _photos_column_cache[board_id] = new_id
            log.info("Created Monday Photos column %s on board %s", new_id, board_id)
            return new_id
    except Exception as exc:
        log.warning("Could not create Monday Photos column: %s", exc)

    return None


async def _upload_photo_to_item(
    client: httpx.AsyncClient,
    token: str,
    item_id: str,
    column_id: str,
    payload: PhotoPayload,
) -> bool:
    filename, content, content_type = payload
    query = (
        f'mutation ($file: File!) {{ add_file_to_column '
        f'(item_id: {item_id}, column_id: "{column_id}", file: $file) '
        f'{{ id }} }}'
    )
    try:
        r = await client.post(
            MONDAY_FILE_URL,
            headers={"Authorization": token, "API-Version": API_VERSION},
            data={"query": query},
            files={"variables[file]": (filename, content, content_type)},
        )
        data = r.json()
        if "errors" in data:
            log.warning("Monday add_file errors for %s: %s", filename, data["errors"])
            return False
        return True
    except Exception as exc:
        log.warning("Monday add_file HTTP error for %s: %s", filename, exc)
        return False


async def push_contact_to_monday(
    record: ContactRequest,
    reference: str,
    board_id: Optional[int] = None,
    photos: Optional[List[PhotoPayload]] = None,
) -> Optional[str]:
    """Create a Monday item for a ContactRequest, with optional photo uploads.

    Returns the new Monday item id on success, or None if disabled or failing.
    Never raises.
    """
    token = settings.monday_api_token
    target_board = board_id or settings.monday_crm_board_id
    if not token or not target_board:
        log.info("Monday bridge disabled: no token or board id configured")
        return None

    item_name = _build_item_name(record)
    update_body = _build_update_body(record, reference, len(photos or []))

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
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            # 1. Create the item
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

            # 2. Attach text details as first update
            try:
                r2 = await client.post(
                    MONDAY_URL,
                    json={
                        "query": update_mutation,
                        "variables": {"itemId": str(item_id), "body": update_body},
                    },
                )
                d2 = r2.json()
                if "errors" in d2:
                    log.warning(
                        "Monday create_update errors on item %s: %s",
                        item_id, d2["errors"],
                    )
            except Exception as exc:
                log.warning("Monday create_update failed on %s: %s", item_id, exc)

            # 3. Upload photos if any
            if photos:
                column_id = await _ensure_photos_column(client, int(target_board))
                if column_id:
                    uploaded = 0
                    for p in photos:
                        ok = await _upload_photo_to_item(
                            client, token, str(item_id), column_id, p
                        )
                        if ok:
                            uploaded += 1
                    log.info(
                        "Uploaded %d/%d photo(s) to Monday item %s (col %s)",
                        uploaded, len(photos), item_id, column_id,
                    )
                else:
                    log.warning(
                        "No Monday Photos column available, skipped %d photo(s)",
                        len(photos),
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
