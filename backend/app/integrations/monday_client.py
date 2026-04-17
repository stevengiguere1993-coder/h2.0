"""
Typed thin client for Monday.com GraphQL v2.

Kept minimal on purpose: we only read during the migration. No mutations,
no subscriptions. Token is taken from MONDAY_API_TOKEN env.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

import httpx

MONDAY_URL = "https://api.monday.com/v2"
API_VERSION = "2024-10"


class MondayClient:
    def __init__(self, token: Optional[str] = None, timeout: float = 30.0):
        self.token = token or os.getenv("MONDAY_API_TOKEN") or ""
        if not self.token:
            raise RuntimeError("MONDAY_API_TOKEN not set")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": self.token,
                "Content-Type": "application/json",
                "API-Version": API_VERSION,
            },
        )

    async def __aenter__(self) -> "MondayClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()

    async def query(
        self, query: str, variables: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"query": query}
        if variables:
            body["variables"] = variables
        # Retry on complexity / rate limit with exponential backoff
        delays = (1, 2, 4, 8)
        last_err: Optional[Exception] = None
        for attempt, delay in enumerate((0, *delays), start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                resp = await self._client.post(MONDAY_URL, json=body)
                data = resp.json()
                if "errors" in data:
                    errors = data["errors"]
                    msg = " / ".join(str(e.get("message")) for e in errors)
                    if any("complexity" in str(e).lower() or "rate" in str(e).lower() for e in errors):
                        last_err = RuntimeError(msg)
                        continue
                    raise RuntimeError(msg)
                resp.raise_for_status()
                return data.get("data", {})
            except (httpx.HTTPError, RuntimeError) as exc:
                last_err = exc
                if attempt == len(delays) + 1:
                    break
        raise last_err or RuntimeError("Monday query failed")

    async def paged_items(self, board_id: int, page_size: int = 100) -> List[Dict[str, Any]]:
        """Fetch all items of a board using items_page cursor pagination."""
        out: List[Dict[str, Any]] = []
        cursor: Optional[str] = None

        q_first = """
        query ($boardId: [ID!]!, $limit: Int!) {
          boards(ids: $boardId) {
            items_page(limit: $limit) {
              cursor
              items {
                id
                name
                group { id title }
                column_values { id type text value }
              }
            }
          }
        }"""

        q_next = """
        query ($cursor: String!, $limit: Int!) {
          next_items_page(cursor: $cursor, limit: $limit) {
            cursor
            items {
              id
              name
              group { id title }
              column_values { id type text value }
            }
          }
        }"""

        data = await self.query(q_first, {"boardId": [str(board_id)], "limit": page_size})
        page = (data.get("boards") or [{}])[0].get("items_page") or {}
        out.extend(page.get("items") or [])
        cursor = page.get("cursor")

        while cursor:
            data = await self.query(q_next, {"cursor": cursor, "limit": page_size})
            page = data.get("next_items_page") or {}
            out.extend(page.get("items") or [])
            cursor = page.get("cursor")

        return out
