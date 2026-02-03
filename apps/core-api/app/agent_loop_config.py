"""Agent Loop configuration module.

This module provides configuration for the Agent Loop feature, including
feature flags, model settings, and whitelist management.
"""

from __future__ import annotations

import os
from typing import List


def _read_bool_env(name: str, default: bool) -> bool:
    """Read boolean environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"0", "false", "off", "no"}:
        return False
    if normalized in {"1", "true", "on", "yes"}:
        return True
    return default


def _read_list_env(name: str, default: List[str]) -> List[str]:
    """Read list environment variable (comma-separated)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    # Split by comma and strip whitespace
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return items if items else default


# Default allowed run types (whitelist)
DEFAULT_ALLOWED_RUN_TYPES = [
    "sleep",
    "summarize_conversation",
    "research_report",
    "edit_docs_propose",
    "edit_docs_apply",
    "edit_docs_cancel",
    # "index_repo",  # Optional, uncomment if needed
    # "fetch_web",   # Optional, uncomment if needed
]

# Agent Loop feature flag
AGENT_LOOP_ENABLED = _read_bool_env("AGENT_LOOP_ENABLED", True)

# Decision model configuration (optional, defaults to chat model)
AGENT_DECISION_MODEL = os.getenv("AGENT_DECISION_MODEL", None)

# Allowed run types whitelist
AGENT_ALLOWED_RUN_TYPES = _read_list_env(
    "AGENT_ALLOWED_RUN_TYPES",
    DEFAULT_ALLOWED_RUN_TYPES
)

# Decision timeout (optional, in seconds)
AGENT_DECISION_TIMEOUT_SECONDS = int(os.getenv("AGENT_DECISION_TIMEOUT_SECONDS", "30"))

# Fallback mode (always "reply-only" for v0.1)
AGENT_DECISION_FALLBACK_MODE = "reply-only"
