"""
Transitional bridge: push incoming contact-form submissions into the
existing Monday.com CRM Soumissions board with full column mapping,
plus a linked Client item in the Clients board.

Failures are logged and swallowed: they must never break the public
contact endpoint.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import List, Optional, Tuple

import httpx

from app.core.config import settings
from app.models.contact_request import ContactRequest

log = logging.getLogger(__name__)

MONDAY_URL = "https://api.monday.com/v2"
MONDAY_FILE_URL = "https://api.monday.com/v2/file"
API_VERSION = "2024-10"

CRM_BOARD_ID_DEFAULT = 18400565505
CLIENTS_BOARD_ID = 18398667742

CRM_COL_NOM_TEXT = "text_mm0ykm8z"
CRM_COL_LIEU = "location_mm0xs8d3"
CRM_COL_TYPE_PROJET = "dropdown_mm0p14e"
CRM_COL_SOURCE_LEAD = "dropdown_mm0pek28"
CRM_COL_BUDGET = "numeric_mm0p2z9b"
CRM_COL_COMMENT = "long_text_mm24zgv"
CRM_COL_DATE = "date_mm0pb57"
CRM_COL_CLIENT_LINK = "board_relation_mm21vrg1"

CLI_COL_EMAIL = "email_mm085sgh"
CLI_COL_PHONE = "phone_mm084c8b"
CLI_COL_LOCATION = "location_mm0aq054"
CLI_COL_TYPE = "color_mm08pyts"

PhotoPayload = Tuple[str, bytes, str]

_photos_column_cache: dict[int, str] = {}


def _type_projet_label(project_type: Optional[str]) -> str:
    if (project_type or "").lower() == "multilogement":
        return "multi-logements"
    return "Residentiel"


def _budget_number(budget_range: Optional[str]) -> Optional[int]:
    mapping = {
        "under_10k": 5000,
        "10_25": 17500,
        "25_50": 37500,
        "50_100": 75000,
        "over_100": 120000,
    }
    return mapping.get((budget_range or "").strip())


def _short_project_title(record: ContactRequest) -> str:
    base = (record.message or "").strip().replace("\n", " ")
    if base:
        return base[:200]
    pt = (record.project_type or "autre").replace("_", " ").title()
    return f"{record.name} - {pt}"[:200]


def _build_update_body(r: ContactRequest, reference: str, photo_count: int) -> str:
    lines = [
        f"Nouvelle demande de contact (reference {reference})",
        "",
        f"Nom: {r.name}",
        f"Courriel: {r.email}",
        f"Telephone: {r.phone or '-'}",
        f"Adresse du projet: {r.address or '-'}",
        f"Type de projet: {r.project_type}",
        f"Budget (fourchette): {r.budget_range or '-'}",
        f"Langue: {r.locale}",
        f"Source: {r.source or 'site-web'}",
        f"Consentement marketing: {'oui' if r.marketing_consent else 'non'}",
        f"Photos jointes: {photo_count}",
        "",
        "Message:",
        r.message or "(aucun)",
    ]
    return "\n".join(lines)


async def _gql(
    client: httpx.AsyncClient, query: str, variables: Optional[dict] = None
) -> dict:
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables
    r = await client.post(MONDAY_URL, json=payload)
    return r.json()


async def _create_client_item(
    client: httpx.AsyncClient, record: ContactRequest
) -> Optional[str]:
    col_values: dict = {
        CLI_COL_TYPE: {"label": "Prospect"},
        CLI_COL_EMAIL: {"email": record.email, "text": record.email},
    }
    if record.phone:
        col_values[CLI_COL_PHONE] = {
            "phone": record.phone,
            "countryShortName": "CA",
        }
    if record.address:
        col_values[CLI_COL_LOCATION] = {"address": record.address}

    mutation = (
        "mutation ($boardId: ID!, $itemName: String!, $columnValues: JSON!) { "
        "create_item(board_id: $boardId, item_name: $itemName, "
        "column_values: $columnValues, create_labels_if_missing: true) { id } }"
    )
    data = await _gql(
        client,
        mutation,
        {
            "boardId": str(CLIENTS_BOARD_ID),
            "itemName": record.name[:250],
            "columnValues": json.dumps(col_values, ensure_ascii=False),
        },
    )
    if "errors" in data:
        log.warning("Monday create Client errors: %s", data["errors"])
        return None
    item_id = (data.get("data", {}).get("create_item") or {}).get("id")
    if item_id:
        log.info("Created Monday Client %s for %s", item_id, record.email)
    return item_id


def _build_crm_column_values(
    record: ContactRequest, client_item_id: Optional[str]
) -> dict:
    col: dict = {
        CRM_COL_NOM_TEXT: record.name,
        CRM_COL_TYPE_PROJET: {"labels": [_type_projet_label(record.project_type)]},
        CRM_COL_SOURCE_LEAD: {"labels": ["Soumission renovation"]},
        CRM_COL_DATE: {"date": date.today().isoformat()},
        CRM_COL_COMMENT: {"text": (record.message or "").strip()},
    }
    if record.address:
        col[CRM_COL_LIEU] = {"address": record.address}
    budget = _budget_number(record.budget_range)
    if budget is not None:
        col[CRM_COL_BUDGET] = str(budget)
    if client_item_id:
        col[CRM_COL_CLIENT_LINK] = {"item_ids": [int(client_item_id)]}
    return col


async def _ensure_photos_column(
    client: httpx.AsyncClient, board_id: int
) -> Optional[str]:
    cached = _photos_column_cache.get(board_id)
    if cached:
        return cached

    try:
        data = await _gql(
            client,
            "query ($boardId: [ID!]!) { boards(ids: $boardId) { "
            "columns { id title type } } }",
            {"boardId": [str(board_id)]},
        )
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

    try:
        data = await _gql(
            client,
            "mutation ($boardId: ID!, $title: String!) { "
            "create_column(board_id: $boardId, title: $title, column_type: file) "
            "{ id } }",
            {"boardId": str(board_id), "title": "Photos"},
        )
        if "errors" in data:
            log.warning("Monday create_column errors: %s", data["errors"])
            return None
        new_id = (data.get("data", {}).get("create_column") or {}).get("id")
        if new_id:
            _photos_column_cache[board_id] = new_id
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
    token = settings.monday_api_token
    target_board = board_id or settings.monday_crm_board_id or CRM_BOARD_ID_DEFAULT
    if not token or not target_board:
        log.info("Monday bridge disabled: no token or board id configured")
        return None

    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "API-Version": API_VERSION,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            client_item_id = await _create_client_item(client, record)

            column_values = _build_crm_column_values(record, client_item_id)
            mutation = (
                "mutation ($boardId: ID!, $itemName: String!, $columnValues: JSON!) { "
                "create_item(board_id: $boardId, item_name: $itemName, "
                "column_values: $columnValues, create_labels_if_missing: true) "
                "{ id } }"
            )
            data = await _gql(
                client,
                mutation,
                {
                    "boardId": str(target_board),
                    "itemName": _short_project_title(record),
                    "columnValues": json.dumps(column_values, ensure_ascii=False),
                },
            )
            if "errors" in data:
                log.warning("Monday create CRM item errors: %s", data["errors"])
                return None
            item_id = (data.get("data", {}).get("create_item") or {}).get("id")
            if not item_id:
                log.warning("Monday create_item returned no id: %s", data)
                return None

            try:
                await _gql(
                    client,
                    "mutation ($itemId: ID!, $body: String!) { "
                    "create_update(item_id: $itemId, body: $body) { id } }",
                    {
                        "itemId": str(item_id),
                        "body": _build_update_body(record, reference, len(photos or [])),
                    },
                )
            except Exception as exc:
                log.warning("Monday create_update failed on %s: %s", item_id, exc)

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
                        "Uploaded %d/%d photo(s) to Monday item %s",
                        uploaded, len(photos), item_id,
                    )
                else:
                    log.warning(
                        "No Monday Photos column available, skipped %d photo(s)",
                        len(photos),
                    )

            log.info(
                "Pushed ContactRequest %s to Monday CRM item %s (client %s)",
                record.id, item_id, client_item_id,
            )
            return str(item_id)
    except httpx.HTTPError as exc:
        log.warning("Monday bridge HTTP error: %s", exc)
        return None
    except json.JSONDecodeError as exc:
        log.warning("Monday bridge JSON decode error: %s", exc)
        return None
    except Exception as exc:
        log.exception("Monday bridge unexpected error: %s", exc)
        return None
