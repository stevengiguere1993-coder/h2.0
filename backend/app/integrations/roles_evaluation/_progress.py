"""État partagé pour la progression des workers d'ingestion.

Le worker (admin_data._provincial_ingest_worker) initialise et lit ce
state. Le module quebec_regional pousse les mises à jour pendant
l'ingestion via update_progress(). Évite un import circulaire.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


_state: dict = {
    "current_file": None,
    "rows_so_far": 0,
    "last_progress_at": None,
}


def reset_progress() -> None:
    _state["current_file"] = None
    _state["rows_so_far"] = 0
    _state["last_progress_at"] = None


def update_progress(
    *,
    current_file: Optional[str] = None,
    rows_so_far: Optional[int] = None,
) -> None:
    if current_file is not None:
        _state["current_file"] = current_file
    if rows_so_far is not None:
        _state["rows_so_far"] = rows_so_far
    _state["last_progress_at"] = datetime.now(timezone.utc).isoformat()


def snapshot() -> dict:
    return dict(_state)
