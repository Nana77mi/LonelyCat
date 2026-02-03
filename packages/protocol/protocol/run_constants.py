"""Shared constants for Run/trace_id. Use same rules in core-api, worker, and UI."""

import re

# 32 lowercase hex (uuid4().hex). Change here when switching to ULID/UUID.
TRACE_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def is_valid_trace_id(s: str | None) -> bool:
    """Return True if s is a valid trace_id (32 lowercase hex)."""
    if not s or not isinstance(s, str):
        return False
    return bool(TRACE_ID_PATTERN.match(s))
