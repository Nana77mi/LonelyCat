"""Tests for facts utility functions."""

import pytest

from agent_worker.utils.facts import fetch_active_facts


class MockMemoryClient:
    """Mock Memory Client for testing."""
    
    def __init__(self, global_facts=None, session_facts=None, project_facts=None):
        self.global_facts = global_facts or []
        self.session_facts = session_facts or {}
        self.project_facts = project_facts or {}
    
    def list_facts(self, scope: str = "global", status: str = "active", 
                   session_id: str = None, project_id: str = None) -> list[dict]:
        if scope == "global":
            return self.global_facts
        elif scope == "session":
            if session_id:
                return self.session_facts.get(session_id, [])
            return []
        elif scope == "project":
            if project_id:
                return self.project_facts.get(project_id, [])
            return []
        return []


def test_fetch_active_facts_global_only():
    """Test fetching global scope facts only."""
    global_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
        {"key": "language", "value": "zh-CN", "status": "active"},
    ]
    client = MockMemoryClient(global_facts=global_facts)
    
    result = fetch_active_facts(client)
    
    assert len(result) == 2
    assert result[0]["key"] == "likes"
    assert result[1]["key"] == "language"


def test_fetch_active_facts_with_session():
    """Test fetching global + session scope facts."""
    global_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
    ]
    session_facts = {
        "conv1": [
            {"key": "current_topic", "value": "python", "status": "active"},
        ]
    }
    client = MockMemoryClient(global_facts=global_facts, session_facts=session_facts)
    
    result = fetch_active_facts(client, conversation_id="conv1")
    
    assert len(result) == 2
    # Check that both global and session facts are present
    keys = {f["key"] for f in result}
    assert "likes" in keys
    assert "current_topic" in keys


def test_fetch_active_facts_session_overrides_global():
    """Test that session scope facts override global scope facts with same key."""
    global_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
    ]
    session_facts = {
        "conv1": [
            {"key": "likes", "value": "dogs", "status": "active"},  # Override
        ]
    }
    client = MockMemoryClient(global_facts=global_facts, session_facts=session_facts)
    
    result = fetch_active_facts(client, conversation_id="conv1")
    
    assert len(result) == 1
    assert result[0]["key"] == "likes"
    assert result[0]["value"] == "dogs"  # Session value overrides global


def test_fetch_active_facts_filters_inactive():
    """Test that inactive facts are filtered out."""
    global_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
        {"key": "old_fact", "value": "old_value", "status": "revoked"},
    ]
    client = MockMemoryClient(global_facts=global_facts)
    
    result = fetch_active_facts(client)
    
    assert len(result) == 1
    assert result[0]["key"] == "likes"


def test_fetch_active_facts_empty():
    """Test fetching facts when none exist."""
    client = MockMemoryClient()
    
    result = fetch_active_facts(client)
    
    assert result == []


def test_fetch_active_facts_no_conversation_id():
    """Test that session facts are not fetched when conversation_id is None."""
    global_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
    ]
    session_facts = {
        "conv1": [
            {"key": "current_topic", "value": "python", "status": "active"},
        ]
    }
    client = MockMemoryClient(global_facts=global_facts, session_facts=session_facts)
    
    result = fetch_active_facts(client, conversation_id=None)
    
    assert len(result) == 1
    assert result[0]["key"] == "likes"


def test_fetch_active_facts_session_error_handling():
    """Test that session fetch errors don't break the function."""
    global_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
    ]
    
    class FailingMemoryClient:
        def list_facts(self, scope: str = "global", status: str = "active", 
                      session_id: str = None, project_id: str = None) -> list[dict]:
            if scope == "global":
                return global_facts
            elif scope == "session":
                raise Exception("Session fetch failed")
            return []
    
    client = FailingMemoryClient()
    
    result = fetch_active_facts(client, conversation_id="conv1")
    
    # Should still return global facts even if session fetch fails
    assert len(result) == 1
    assert result[0]["key"] == "likes"


def test_fetch_active_facts_global_error_handling():
    """Test that global fetch errors return empty list."""
    class FailingMemoryClient:
        def list_facts(self, scope: str = "global", status: str = "active", 
                      session_id: str = None, project_id: str = None) -> list[dict]:
            raise Exception("Global fetch failed")
    
    client = FailingMemoryClient()
    
    result = fetch_active_facts(client)
    
    assert result == []


def test_fetch_active_facts_deduplication_by_key():
    """Test that facts are deduplicated by key (session overrides global)."""
    global_facts = [
        {"key": "key1", "value": "global_value", "status": "active"},
        {"key": "key2", "value": "global_value2", "status": "active"},
    ]
    session_facts = {
        "conv1": [
            {"key": "key1", "value": "session_value", "status": "active"},  # Override
            {"key": "key3", "value": "session_value3", "status": "active"},  # New
        ]
    }
    client = MockMemoryClient(global_facts=global_facts, session_facts=session_facts)
    
    result = fetch_active_facts(client, conversation_id="conv1")
    
    assert len(result) == 3
    # Check that key1 has session value
    key1_fact = next(f for f in result if f["key"] == "key1")
    assert key1_fact["value"] == "session_value"
    # Check all keys are present
    keys = {f["key"] for f in result}
    assert keys == {"key1", "key2", "key3"}
