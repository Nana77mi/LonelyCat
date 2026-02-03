"""Tests for shared facts formatting (utils.facts_format) and responder integration."""

import json
import re

from agent_worker.responder import Responder
from agent_worker.persona import PersonaRegistry
from agent_worker.utils.facts_format import (
    format_facts_block,
    compute_facts_snapshot_id,
    format_facts_and_snapshot,
)


def test_format_facts_block_empty():
    """Test formatting empty facts list."""
    result = format_facts_block([])
    assert result == ""


def test_format_facts_block_no_active():
    """Test formatting facts list with no active facts."""
    facts = [
        {"key": "likes", "value": "cats", "status": "revoked"},
    ]
    result = format_facts_block(facts)
    assert result == ""


def test_format_facts_block_simple():
    """Test formatting simple facts."""
    facts = [
        {"key": "likes", "value": "cats", "status": "active"},
        {"key": "language", "value": "zh-CN", "status": "active"},
    ]
    result = format_facts_block(facts)
    
    assert "[KNOWN FACTS]" in result
    assert "[/KNOWN FACTS]" in result
    assert "Rules:" in result
    assert "- likes: cats" in result
    assert "- language: zh-CN" in result
    assert "Use KNOWN FACTS when relevant" in result
    assert "Do not ask for info already in KNOWN FACTS" in result
    assert "If user contradicts a fact" in result


def test_format_facts_block_complex_value_dict():
    """Test formatting facts with dict values."""
    facts = [
        {"key": "preferences", "value": {"theme": "dark", "font": "mono"}, "status": "active"},
    ]
    result = format_facts_block(facts)
    
    assert "- preferences:" in result
    # Value should be JSON serialized
    value_str = json.dumps({"theme": "dark", "font": "mono"}, sort_keys=True, ensure_ascii=False)
    assert value_str in result


def test_format_facts_block_complex_value_list():
    """Test formatting facts with list values."""
    facts = [
        {"key": "favorites", "value": ["apple", "banana"], "status": "active"},
    ]
    result = format_facts_block(facts)
    
    assert "- favorites:" in result
    # Value should be JSON serialized
    value_str = json.dumps(["apple", "banana"], sort_keys=True, ensure_ascii=False)
    assert value_str in result


def test_format_facts_block_mixed_status():
    """Test formatting facts with mixed active/inactive status."""
    facts = [
        {"key": "likes", "value": "cats", "status": "active"},
        {"key": "old", "value": "value", "status": "revoked"},
        {"key": "language", "value": "zh-CN", "status": "active"},
    ]
    result = format_facts_block(facts)
    
    assert "- likes: cats" in result
    assert "- language: zh-CN" in result
    assert "- old: value" not in result  # Revoked fact should not appear


def test_reply_with_messages_injects_facts_in_system_not_user():
    """Facts must be in system message, not in user message (Phase 1.1)."""
    captured_messages = []

    class CaptureLLM:
        def generate(self, prompt: str) -> str:
            return "Okay."
        def generate_messages(self, messages: list) -> str:
            captured_messages.extend(messages)
            return json.dumps({"assistant_reply": "Okay.", "memory": "NO_ACTION"})

    responder = Responder(CaptureLLM())
    persona = PersonaRegistry.load_default().default()
    active_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
        {"key": "language", "value": "zh-CN", "status": "active"},
    ]
    responder.reply_with_messages(
        persona=persona,
        user_message="What do I like?",
        history_messages=[],
        active_facts=active_facts,
    )
    assert len(captured_messages) >= 2
    system_msg = next((m for m in captured_messages if m.get("role") == "system"), None)
    user_msg = next((m for m in captured_messages if m.get("role") == "user"), None)
    assert system_msg is not None, "must have a system message"
    assert user_msg is not None, "must have a user message"
    assert "[KNOWN FACTS]" in system_msg["content"]
    assert "- likes: cats" in system_msg["content"]
    assert "- language: zh-CN" in system_msg["content"]
    assert "active_facts" not in user_msg["content"]
    assert user_msg["content"].strip() == "user_message: What do I like?"


# --- compute_facts_snapshot_id (content hash, stable and comparable) ---

_HEX_64 = re.compile(r"^[a-f0-9]{64}$")


def test_compute_facts_snapshot_id_empty():
    """Empty facts → deterministic hex snapshot_id."""
    sid = compute_facts_snapshot_id([])
    assert _HEX_64.match(sid), "snapshot_id must be 64-char hex"


def test_compute_facts_snapshot_id_same_facts_same_id():
    """Same fact set → same snapshot_id (predictable for replay)."""
    facts = [
        {"key": "likes", "value": "cats", "status": "active"},
        {"key": "language", "value": "zh-CN", "status": "active"},
    ]
    a = compute_facts_snapshot_id(facts)
    b = compute_facts_snapshot_id(facts)
    assert a == b
    assert _HEX_64.match(a)


def test_compute_facts_snapshot_id_order_independent():
    """Different input order, same content → same snapshot_id (canonical sort)."""
    facts1 = [
        {"key": "likes", "value": "cats", "status": "active"},
        {"key": "language", "value": "zh-CN", "status": "active"},
    ]
    facts2 = [
        {"key": "language", "value": "zh-CN", "status": "active"},
        {"key": "likes", "value": "cats", "status": "active"},
    ]
    assert compute_facts_snapshot_id(facts1) == compute_facts_snapshot_id(facts2)


def test_compute_facts_snapshot_id_different_facts_different_id():
    """Any change → snapshot_id changes."""
    facts_a = [{"key": "likes", "value": "cats", "status": "active"}]
    facts_b = [{"key": "likes", "value": "dogs", "status": "active"}]
    facts_c = [{"key": "language", "value": "zh-CN", "status": "active"}]
    id_a = compute_facts_snapshot_id(facts_a)
    id_b = compute_facts_snapshot_id(facts_b)
    id_c = compute_facts_snapshot_id(facts_c)
    assert id_a != id_b
    assert id_a != id_c
    assert id_b != id_c


def test_format_facts_and_snapshot_returns_text_and_id():
    """format_facts_and_snapshot returns (facts_text, snapshot_id) for one-shot use."""
    facts = [{"key": "likes", "value": "cats", "status": "active"}]
    text, sid = format_facts_and_snapshot(facts)
    assert "[KNOWN FACTS]" in text
    assert "- likes: cats" in text
    assert _HEX_64.match(sid), "snapshot_id must be 64-char hex"
    assert sid == compute_facts_snapshot_id(facts)

    # Same fact set (order shuffled) → same snapshot_id (稳定可比对)
    facts_two = [
        {"key": "language", "value": "zh-CN", "status": "active"},
        {"key": "likes", "value": "cats", "status": "active"},
    ]
    _, sid_two_a = format_facts_and_snapshot(facts_two)
    _, sid_two_b = format_facts_and_snapshot([facts_two[1], facts_two[0]])
    assert sid_two_a == sid_two_b, "same set, different order → same snapshot_id"

    # Add one fact → snapshot_id changes
    facts_extra = facts + [{"key": "language", "value": "zh-CN", "status": "active"}]
    _, sid_extra = format_facts_and_snapshot(facts_extra)
    assert sid_extra != sid

    # Remove one fact → snapshot_id changes (empty vs one)
    _, sid_empty = format_facts_and_snapshot([])
    assert sid_empty != sid

    # Change one value → snapshot_id changes
    facts_changed = [{"key": "likes", "value": "dogs", "status": "active"}]
    _, sid_changed = format_facts_and_snapshot(facts_changed)
    assert sid_changed != sid
