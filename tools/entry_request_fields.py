"""
Shared entry-request field handling for ingest and tools.

Entry JSON uses ``requested_entry_time``; sub-agent tool JSON uses ``entry_time``.
"""

from __future__ import annotations

from typing import Any, Dict


def normalize_entry_request_dict(request: Dict[str, Any]) -> None:
    """
    Mutate ``request`` in place: if ``entry_time`` is missing but
    ``requested_entry_time`` is set, copy it to ``entry_time`` so orchestrator
    text and tools see one canonical instant.
    """
    if request.get("entry_time") is None and request.get("requested_entry_time") is not None:
        request["entry_time"] = str(request["requested_entry_time"]).strip()


def entry_time_iso(data: Dict[str, Any]) -> str:
    """
    Return the ISO8601 entry time for tool payloads.

    Accepts either ``entry_time`` or ``requested_entry_time`` (same instant,
    different key names). Raises ``ValueError`` if neither is present and non-empty.
    """
    et = data.get("entry_time")
    if et is not None and str(et).strip():
        return str(et).strip()
    ret = data.get("requested_entry_time")
    if ret is not None and str(ret).strip():
        return str(ret).strip()
    raise ValueError(
        "Tool input must include entry_time or requested_entry_time (ISO8601 string)."
    )
