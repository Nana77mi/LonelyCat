"""Shared facts formatting and canonical snapshot ID for chat/runner/trace.

All fact block formatting and snapshot_id computation live here so chat_flow,
responder, and runner stay in sync (no copy-paste drift).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def format_facts_block(active_facts: list[dict]) -> str:
    """Format active facts for injection into system message.

    Only includes facts with status 'active'. Returns empty string if none.
    Used by responder (chat) and runner (summarize) so the block is identical.
    """
    lines = []
    for f in active_facts:
        if f.get("status") != "active":
            continue
        key = f.get("key", "")
        if not key:
            continue
        val = f.get("value")
        if isinstance(val, (dict, list)):
            val_str = json.dumps(val, sort_keys=True, ensure_ascii=False)
        else:
            val_str = str(val) if val is not None else ""
        lines.append(f"- {key}: {val_str}")
    if not lines:
        return ""
    block = "\n".join(lines)
    return (
        "The following are known facts about the user.\n"
        "You MUST use them when relevant and MUST NOT ask the user for information already stated here.\n\n"
        "[KNOWN FACTS]\n"
        f"{block}\n"
        "[/KNOWN FACTS]\n\n"
        "Rules:\n"
        "- Use KNOWN FACTS when relevant.\n"
        "- Do not ask for info already in KNOWN FACTS.\n"
        "- If user contradicts a fact, acknowledge and do not argue.\n"
    )


def _canonical_value(value: Any) -> str:
    """Stable string for a fact value (for hashing)."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def compute_facts_snapshot_id(active_facts: list[dict]) -> str:
    """Compute a stable, content-based snapshot ID for a set of active facts.

    Same fact set → same snapshot_id. Any change → different snapshot_id.
    Canonical rules (must match core-api app.services.facts.compute_facts_snapshot_id):
    - Only status=="active", non-empty key.
    - Sort by (id or ""), then key.
    - Canonical uses only stable fields: id, key, value. Do NOT include created_at,
      updated_at, source_ref, etc., or snapshot would change on every update.
    Returns 64-char hex string (SHA-256).
    """
    active = [f for f in active_facts if f.get("status") == "active" and f.get("key")]
    ordered = sorted(
        active,
        key=lambda f: (f.get("id") or "", f.get("key") or ""),
    )
    # Fixed field order per fact for stable JSON
    canonical_list = [
        {
            "id": f.get("id"),
            "key": f.get("key"),
            "value": _canonical_value(f.get("value")),
        }
        for f in ordered
    ]
    canonical_json = json.dumps(
        canonical_list,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def format_facts_and_snapshot(active_facts: list[dict]) -> tuple[str, str]:
    """Return (facts_text, snapshot_id) for one-shot injection and trace.

    Same snapshot → same id; use for "同一 snapshot 的注入方式" and replay.
    """
    return (format_facts_block(active_facts), compute_facts_snapshot_id(active_facts))
