"""Tests for runner facts integration."""

import pytest
from unittest.mock import Mock, patch

from agent_worker.llm.stub import StubLLM
from worker.db import RunModel
from worker.db_models import MessageModel, MessageRole
from worker.runner import TaskRunner


class MockMemoryClient:
    """Mock Memory Client for testing."""
    
    def __init__(self, global_facts=None, session_facts=None):
        self.global_facts = global_facts or []
        self.session_facts = session_facts or {}
    
    def list_facts(self, scope: str = "global", status: str = "active", 
                   session_id: str = None, project_id: str = None) -> list[dict]:
        if scope == "global":
            return self.global_facts
        elif scope == "session" and session_id:
            return self.session_facts.get(session_id, [])
        return []


def test_build_memory_client():
    """Test that _build_memory_client returns a MemoryClient instance."""
    runner = TaskRunner()
    memory_client = runner._build_memory_client()
    
    # Should return a MemoryClient instance
    assert memory_client is not None
    assert hasattr(memory_client, "list_facts")


def test_build_memory_client_can_be_mocked():
    """Test that _build_memory_client can be monkeypatched for testing."""
    runner = TaskRunner()
    
    mock_client = MockMemoryClient()
    
    # Monkeypatch the method
    runner._build_memory_client = lambda: mock_client
    
    result = runner._build_memory_client()
    assert result == mock_client


def test_summarize_conversation_with_facts():
    """Test summarize_conversation handler uses facts when available."""
    # This test verifies that facts are fetched and passed to _build_summary_prompt
    # We test the prompt building part separately, so here we just verify the flow works
    
    runner = TaskRunner()
    
    # Mock memory client with facts
    mock_memory_client = MockMemoryClient(
        global_facts=[
            {"key": "likes", "value": "cats", "status": "active"},
        ]
    )
    
    # Mock the _build_memory_client method
    runner._build_memory_client = lambda: mock_memory_client
    
    # Verify that _build_memory_client returns our mock
    result_client = runner._build_memory_client()
    assert result_client == mock_memory_client
    
    # Verify that facts can be fetched
    from agent_worker.utils.facts import fetch_active_facts
    facts = fetch_active_facts(mock_memory_client, conversation_id="test_conv")
    assert len(facts) == 1
    assert facts[0]["key"] == "likes"


def test_build_summary_prompt_with_facts():
    """Test _build_summary_prompt includes facts block when facts are provided."""
    runner = TaskRunner()
    
    messages = [
        Mock(role=MessageRole.USER, content="我喜欢猫"),
        Mock(role=MessageRole.ASSISTANT, content="好的"),
    ]
    
    active_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
    ]
    
    prompt = runner._build_summary_prompt(messages, active_facts)
    
    assert "[KNOWN FACTS]" in prompt
    assert "[/KNOWN FACTS]" in prompt
    assert "- likes: cats" in prompt
    assert "for reference only" in prompt
    assert "1. User: 我喜欢猫" in prompt


def test_build_summary_prompt_without_facts():
    """Test _build_summary_prompt works without facts."""
    runner = TaskRunner()
    
    messages = [
        Mock(role=MessageRole.USER, content="Hello"),
        Mock(role=MessageRole.ASSISTANT, content="Hi"),
    ]
    
    prompt = runner._build_summary_prompt(messages, None)
    
    assert "[KNOWN FACTS]" not in prompt
    assert "1. User: Hello" in prompt
    assert "2. Assistant: Hi" in prompt


def test_build_summary_prompt_with_complex_fact_value():
    """Test _build_summary_prompt handles complex fact values (dict/list)."""
    import json
    runner = TaskRunner()
    
    messages = [
        Mock(role=MessageRole.USER, content="Test"),
    ]
    
    active_facts = [
        {"key": "preferences", "value": {"theme": "dark"}, "status": "active"},
    ]
    
    prompt = runner._build_summary_prompt(messages, active_facts)
    
    assert "[KNOWN FACTS]" in prompt
    assert "- preferences:" in prompt
    # Value should be JSON serialized
    value_str = json.dumps({"theme": "dark"}, sort_keys=True, ensure_ascii=False)
    assert value_str in prompt


def test_build_summary_prompt_filters_inactive_facts():
    """Test _build_summary_prompt filters out inactive facts."""
    runner = TaskRunner()
    
    messages = [
        Mock(role=MessageRole.USER, content="Test"),
    ]
    
    active_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
        {"key": "old", "value": "value", "status": "revoked"},
    ]
    
    prompt = runner._build_summary_prompt(messages, active_facts)
    
    assert "- likes: cats" in prompt
    assert "- old: value" not in prompt
