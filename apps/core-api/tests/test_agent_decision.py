"""Tests for Agent Decision service."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add agent-worker path for imports
agent_worker_path = Path(__file__).parent.parent.parent / "agent-worker"
if str(agent_worker_path) not in sys.path:
    sys.path.insert(0, str(agent_worker_path))

from agent_worker.llm.base import BaseLLM
from agent_worker.llm.json_only import JsonOnlyLLMWrapper

from app.services.agent_decision import AgentDecision, Decision, ReplyContent, RunDecision


class MockLLM(BaseLLM):
    """Mock LLM for testing."""
    
    def __init__(self, response: str):
        super().__init__()
        self.response = response
    
    def generate(self, prompt: str) -> str:
        return self.response
    
    def generate_messages(self, messages: list[dict[str, str]]) -> str:
        return self.response


class MockMemoryClient:
    """Mock Memory Client for testing."""
    
    def __init__(self, facts: list[dict] = None):
        self.facts = facts or []
    
    def list_facts(self, scope: str = "global", status: str = "active", 
                   session_id: str = None, project_id: str = None) -> list[dict]:
        return self.facts


def test_decision_validation_reply_only():
    """Test Decision validation for reply-only."""
    decision = Decision(
        decision="reply",
        reply=ReplyContent(content="Test reply"),
        run=None,
        confidence=0.8,
        reason="User asked a question",
    )
    is_valid, error_msg = decision.validate_decision_logic()
    assert is_valid is True
    assert error_msg is None


def test_decision_validation_reply_missing_reply():
    """Test Decision validation fails when reply is missing for reply decision."""
    decision = Decision(
        decision="reply",
        reply=None,
        run=None,
        confidence=0.8,
        reason="Test",
    )
    is_valid, error_msg = decision.validate_decision_logic()
    assert is_valid is False
    assert "requires 'reply' field" in error_msg


def test_decision_validation_reply_with_run():
    """Test Decision validation fails when reply has run field."""
    decision = Decision(
        decision="reply",
        reply=ReplyContent(content="Test"),
        run=RunDecision(type="sleep", input={"seconds": 5}),
        confidence=0.8,
        reason="Test",
    )
    is_valid, error_msg = decision.validate_decision_logic()
    assert is_valid is False
    assert "should not have 'run' field" in error_msg


def test_decision_validation_run_only():
    """Test Decision validation for run-only."""
    decision = Decision(
        decision="run",
        reply=None,
        run=RunDecision(type="sleep", input={"seconds": 5}),
        confidence=0.9,
        reason="User wants to sleep",
    )
    is_valid, error_msg = decision.validate_decision_logic()
    assert is_valid is True
    assert error_msg is None


def test_decision_validation_run_missing_run():
    """Test Decision validation fails when run is missing for run decision."""
    decision = Decision(
        decision="run",
        reply=None,
        run=None,
        confidence=0.9,
        reason="Test",
    )
    is_valid, error_msg = decision.validate_decision_logic()
    assert is_valid is False
    assert "requires 'run' field" in error_msg


def test_decision_validation_reply_and_run():
    """Test Decision validation for reply_and_run."""
    decision = Decision(
        decision="reply_and_run",
        reply=ReplyContent(content="I'll start the task"),
        run=RunDecision(type="sleep", input={"seconds": 5}),
        confidence=0.95,
        reason="User wants both reply and task",
    )
    is_valid, error_msg = decision.validate_decision_logic()
    assert is_valid is True
    assert error_msg is None


def test_decision_validation_reply_and_run_missing_reply():
    """Test Decision validation fails when reply_and_run is missing reply."""
    decision = Decision(
        decision="reply_and_run",
        reply=None,
        run=RunDecision(type="sleep", input={"seconds": 5}),
        confidence=0.95,
        reason="Test",
    )
    is_valid, error_msg = decision.validate_decision_logic()
    assert is_valid is False
    assert "requires 'reply' field" in error_msg


def test_decision_validation_reply_and_run_missing_run():
    """Test Decision validation fails when reply_and_run is missing run."""
    decision = Decision(
        decision="reply_and_run",
        reply=ReplyContent(content="Test"),
        run=None,
        confidence=0.95,
        reason="Test",
    )
    is_valid, error_msg = decision.validate_decision_logic()
    assert is_valid is False
    assert "requires 'run' field" in error_msg


@patch("app.services.agent_decision.AGENT_WORKER_AVAILABLE", True)
def test_agent_decision_decide_reply_only():
    """Test AgentDecision.decide() with reply-only decision."""
    # Mock LLM response
    decision_json = {
        "decision": "reply",
        "reply": {"content": "Hello, how can I help you?"},
        "run": None,
        "confidence": 0.9,
        "reason": "User asked a question",
    }
    mock_llm = MockLLM(json.dumps(decision_json))
    
    # Create AgentDecision with mocked LLM
    agent_decision = AgentDecision()
    agent_decision._llm = JsonOnlyLLMWrapper(mock_llm)
    agent_decision._memory_client = MockMemoryClient()
    
    # Make decision
    decision = agent_decision.decide(
        user_message="Hello",
        conversation_id="test-conv-1",
        history_messages=[],
        active_facts=[],
        recent_runs=[],
    )
    
    assert decision.decision == "reply"
    assert decision.reply is not None
    assert decision.reply.content == "Hello, how can I help you?"
    assert decision.run is None


@patch("app.services.agent_decision.AGENT_WORKER_AVAILABLE", True)
def test_agent_decision_decide_run_only():
    """Test AgentDecision.decide() with run-only decision."""
    # Mock LLM response
    decision_json = {
        "decision": "run",
        "reply": None,
        "run": {
            "type": "sleep",
            "title": "Sleep 5 seconds",
            "conversation_id": "test-conv-1",
            "input": {"seconds": 5},
        },
        "confidence": 0.95,
        "reason": "User wants to sleep",
    }
    mock_llm = MockLLM(json.dumps(decision_json))
    
    # Create AgentDecision with mocked LLM
    agent_decision = AgentDecision()
    agent_decision._llm = JsonOnlyLLMWrapper(mock_llm)
    agent_decision._memory_client = MockMemoryClient()
    
    # Make decision
    decision = agent_decision.decide(
        user_message="Sleep for 5 seconds",
        conversation_id="test-conv-1",
        history_messages=[],
        active_facts=[],
        recent_runs=[],
    )
    
    assert decision.decision == "run"
    assert decision.run is not None
    assert decision.run.type == "sleep"
    assert decision.run.title == "Sleep 5 seconds"
    assert decision.run.conversation_id == "test-conv-1"
    assert decision.run.input == {"seconds": 5}


@patch("app.services.agent_decision.AGENT_WORKER_AVAILABLE", True)
def test_agent_decision_decide_reply_and_run():
    """Test AgentDecision.decide() with reply_and_run decision."""
    # Mock LLM response
    decision_json = {
        "decision": "reply_and_run",
        "reply": {"content": "I'll start the sleep task for you."},
        "run": {
            "type": "sleep",
            "title": "Sleep 5 seconds",
            "conversation_id": "test-conv-1",
            "input": {"seconds": 5},
        },
        "confidence": 0.98,
        "reason": "User wants both reply and task",
    }
    mock_llm = MockLLM(json.dumps(decision_json))
    
    # Create AgentDecision with mocked LLM
    agent_decision = AgentDecision()
    agent_decision._llm = JsonOnlyLLMWrapper(mock_llm)
    agent_decision._memory_client = MockMemoryClient()
    
    # Make decision
    decision = agent_decision.decide(
        user_message="Please sleep for 5 seconds",
        conversation_id="test-conv-1",
        history_messages=[],
        active_facts=[],
        recent_runs=[],
    )
    
    assert decision.decision == "reply_and_run"
    assert decision.reply is not None
    assert decision.reply.content == "I'll start the sleep task for you."
    assert decision.run is not None
    assert decision.run.type == "sleep"


@patch("app.services.agent_decision.AGENT_WORKER_AVAILABLE", True)
def test_agent_decision_whitelist_fallback():
    """Test AgentDecision falls back to reply-only when run type is not in whitelist."""
    # Mock LLM response with invalid run type
    decision_json = {
        "decision": "run",
        "reply": None,
        "run": {
            "type": "invalid_task_type",
            "title": "Invalid task",
            "conversation_id": "test-conv-1",
            "input": {},
        },
        "confidence": 0.9,
        "reason": "Test",
    }
    mock_llm = MockLLM(json.dumps(decision_json))
    
    # Create AgentDecision with mocked LLM
    agent_decision = AgentDecision()
    agent_decision._llm = JsonOnlyLLMWrapper(mock_llm)
    agent_decision._memory_client = MockMemoryClient()
    
    # Make decision
    decision = agent_decision.decide(
        user_message="Do something invalid",
        conversation_id="test-conv-1",
        history_messages=[],
        active_facts=[],
        recent_runs=[],
    )
    
    # Should fallback to reply-only
    assert decision.decision == "reply"
    assert decision.reply is not None
    assert "不在允许列表中" in decision.reply.content
    assert decision.run is None


@patch("app.services.agent_decision.AGENT_WORKER_AVAILABLE", True)
def test_agent_decision_conversation_id_set():
    """Test AgentDecision sets conversation_id correctly."""
    # Mock LLM response with null conversation_id
    decision_json = {
        "decision": "run",
        "reply": None,
        "run": {
            "type": "sleep",
            "title": "Sleep",
            "conversation_id": None,  # LLM returned null
            "input": {"seconds": 5},
        },
        "confidence": 0.9,
        "reason": "Test",
    }
    mock_llm = MockLLM(json.dumps(decision_json))
    
    # Create AgentDecision with mocked LLM
    agent_decision = AgentDecision()
    agent_decision._llm = JsonOnlyLLMWrapper(mock_llm)
    agent_decision._memory_client = MockMemoryClient()
    
    # Make decision
    decision = agent_decision.decide(
        user_message="Sleep",
        conversation_id="test-conv-1",
        history_messages=[],
        active_facts=[],
        recent_runs=[],
    )
    
    # Should set conversation_id to current conversation
    assert decision.run is not None
    assert decision.run.conversation_id == "test-conv-1"


@patch("app.services.agent_decision.AGENT_WORKER_AVAILABLE", True)
def test_agent_decision_invalid_json():
    """Test AgentDecision handles invalid JSON gracefully."""
    mock_llm = MockLLM("Invalid JSON response")
    
    # Create AgentDecision with mocked LLM
    agent_decision = AgentDecision()
    agent_decision._llm = JsonOnlyLLMWrapper(mock_llm)
    agent_decision._memory_client = MockMemoryClient()
    
    # Should raise ValueError
    with pytest.raises(ValueError, match="Invalid JSON"):
        agent_decision.decide(
            user_message="Test",
            conversation_id="test-conv-1",
            history_messages=[],
            active_facts=[],
            recent_runs=[],
        )


@patch("app.services.agent_decision.AGENT_WORKER_AVAILABLE", True)
def test_agent_decision_invalid_schema():
    """Test AgentDecision handles invalid schema gracefully."""
    # Mock LLM response with invalid schema (missing required fields)
    decision_json = {
        "decision": "reply",
        # Missing reply field
    }
    mock_llm = MockLLM(json.dumps(decision_json))
    
    # Create AgentDecision with mocked LLM
    agent_decision = AgentDecision()
    agent_decision._llm = JsonOnlyLLMWrapper(mock_llm)
    agent_decision._memory_client = MockMemoryClient()
    
    # Should raise ValueError (either schema validation or logic validation)
    with pytest.raises(ValueError, match="validation failed"):
        agent_decision.decide(
            user_message="Test",
            conversation_id="test-conv-1",
            history_messages=[],
            active_facts=[],
            recent_runs=[],
        )


@patch("app.services.agent_decision.AGENT_WORKER_AVAILABLE", True)
def test_agent_decision_build_prompt():
    """Test AgentDecision._build_decision_prompt() includes all context."""
    agent_decision = AgentDecision()
    agent_decision._llm = MockLLM("")
    agent_decision._memory_client = MockMemoryClient()
    
    history_messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    active_facts = [
        {"key": "user_name", "value": "Alice"},
    ]
    recent_runs = [
        {"type": "sleep", "status": "succeeded"},
    ]
    
    prompt = agent_decision._build_decision_prompt(
        user_message="Test message",
        conversation_id="test-conv-1",
        history_messages=history_messages,
        active_facts=active_facts,
        recent_runs=recent_runs,
    )
    
    # Check prompt includes all context
    assert "Test message" in prompt
    assert "test-conv-1" in prompt
    assert "Hello" in prompt
    assert "Hi there!" in prompt
    assert "user_name" in prompt or "Alice" in prompt
    assert "sleep" in prompt


@patch("app.services.agent_decision.AGENT_WORKER_AVAILABLE", True)
def test_agent_decision_prompt_includes_run_code_snippet_rule_and_example():
    """决策 prompt 包含 run_code_snippet 的规则与示例，便于 LLM 在用户要求跑代码时产出正确 run.input。"""
    agent_decision = AgentDecision()
    agent_decision._llm = MockLLM("")
    agent_decision._memory_client = MockMemoryClient()

    prompt = agent_decision._build_decision_prompt(
        user_message="帮我跑这段代码",
        conversation_id="conv-1",
        history_messages=[],
        active_facts=[],
        recent_runs=[],
    )

    assert "run_code_snippet" in prompt
    assert "language" in prompt
    assert "code" in prompt or "script" in prompt
    # 应有示例：用户说跑代码 -> type=run_code_snippet, run.input 含 language/code 等
    assert "python" in prompt or "shell" in prompt
    assert "run.input" in prompt or "input" in prompt


@patch("app.services.agent_decision.AGENT_WORKER_AVAILABLE", True)
@patch("app.services.agent_decision.fetch_active_facts")
def test_agent_decision_get_active_facts(mock_fetch_active_facts):
    """Test AgentDecision.get_active_facts() returns facts from memory client."""
    global_facts = [
        {"key": "fact1", "value": "value1", "status": "active"},
        {"key": "fact2", "value": "value2", "status": "active"},
    ]
    mock_fetch_active_facts.return_value = global_facts
    mock_memory_client = MockMemoryClient(facts=global_facts)
    
    agent_decision = AgentDecision()
    agent_decision._memory_client = mock_memory_client
    
    result = agent_decision.get_active_facts()
    assert result == global_facts
    assert len(result) == 2
    assert result[0]["key"] == "fact1"
    assert result[1]["key"] == "fact2"


@patch("app.services.agent_decision.AGENT_WORKER_AVAILABLE", True)
@patch("app.services.agent_decision.fetch_active_facts")
def test_agent_decision_get_active_facts_with_conversation_id(mock_fetch_active_facts):
    """Test AgentDecision.get_active_facts() with conversation_id for session scope."""
    global_facts = [
        {"key": "fact1", "value": "value1", "status": "active"},
    ]
    session_facts = [
        {"key": "fact2", "value": "value2", "status": "active"},
    ]
    merged = global_facts + session_facts  # expected: both scopes
    mock_fetch_active_facts.return_value = merged
    
    class MockMemoryClientWithSession:
        def __init__(self):
            self.global_facts = global_facts
            self.session_facts = {"conv1": session_facts}
        
        def list_facts(self, scope: str = "global", status: str = "active",
                      session_id: str = None, project_id: str = None) -> list[dict]:
            if scope == "global":
                return self.global_facts
            elif scope == "session" and session_id:
                return self.session_facts.get(session_id, [])
            return []
    
    mock_memory_client = MockMemoryClientWithSession()
    agent_decision = AgentDecision()
    agent_decision._memory_client = mock_memory_client
    
    result = agent_decision.get_active_facts(conversation_id="conv1")
    assert len(result) == 2
    keys = {f["key"] for f in result}
    assert "fact1" in keys
    assert "fact2" in keys


@patch("app.services.agent_decision.AGENT_WORKER_AVAILABLE", False)
def test_agent_decision_unavailable():
    """Test AgentDecision initialization when agent_worker is unavailable."""
    agent_decision = AgentDecision()
    assert agent_decision._llm is None
    assert agent_decision._memory_client is None
    
    # Should raise ValueError when trying to decide
    with pytest.raises(ValueError, match="not available"):
        agent_decision.decide(
            user_message="Test",
            conversation_id="test-conv-1",
            history_messages=[],
            active_facts=[],
            recent_runs=[],
        )


@patch("app.services.agent_decision.AGENT_WORKER_AVAILABLE", True)
def test_agent_decision_empty_llm_response():
    """Test AgentDecision handles empty/invalid LLM response."""
    # JsonOnlyLLMWrapper returns "NO_ACTION" for empty/invalid responses
    mock_llm = MockLLM("")
    
    agent_decision = AgentDecision()
    agent_decision._llm = JsonOnlyLLMWrapper(mock_llm)
    agent_decision._memory_client = MockMemoryClient()
    
    # Should raise ValueError (either empty response or invalid JSON)
    with pytest.raises(ValueError):
        agent_decision.decide(
            user_message="Test",
            conversation_id="test-conv-1",
            history_messages=[],
            active_facts=[],
            recent_runs=[],
        )
