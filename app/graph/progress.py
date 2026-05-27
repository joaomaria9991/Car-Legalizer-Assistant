from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.models.state import ProcessState


AGENT_PROGRESS_FLAG = "agent_progress"
MAX_PROGRESS_ENTRIES = 200


def add_progress(
    state: ProcessState,
    stage: str,
    status: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state.flags = state.flags or {}
    progress = state.flags.setdefault(AGENT_PROGRESS_FLAG, [])
    if not isinstance(progress, list):
        progress = []
        state.flags[AGENT_PROGRESS_FLAG] = progress

    entry: dict[str, Any] = {
        "id": uuid4().hex,
        "stage": stage,
        "status": status,
        "message": message,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if detail:
        entry["detail"] = detail

    progress.append(entry)
    if len(progress) > MAX_PROGRESS_ENTRIES:
        del progress[:-MAX_PROGRESS_ENTRIES]
    return entry


def start_progress(
    state: ProcessState,
    stage: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return add_progress(state, stage, "running", message, detail)


def finish_progress(
    state: ProcessState,
    stage: str,
    message: str,
    detail: dict[str, Any] | None = None,
    status: str = "done",
) -> dict[str, Any]:
    return add_progress(state, stage, status, message, detail)
