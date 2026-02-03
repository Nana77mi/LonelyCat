"""Additional Agent Loop tests (Priority Order)."""

import asyncio
import json
import logging
import os
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

from app.api import conversations
from app.db import Base, ConversationModel, MessageModel, MessageRole, RunModel, RunStatus

# Add agent-worker path for imports
agent_worker_path = Path(__file__).parent.parent.parent / "agent-worker"
if str(agent_worker_path) not in sys.path:
    sys.path.insert(0, str(agent_worker_path))


def _commit_db(db):
    """辅助函数：提交数据库事务"""
    db.commit()


@pytest.fixture
def temp_db():
    """创建临时数据库用于测试"""
    # 创建临时数据库文件
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    # 创建临时数据库 engine
    test_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=test_engine)
    
    # 创建测试会话
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestSessionLocal()
    
    yield db, db_path
    
    # 清理
    db.close()
    os.unlink(db_path)


@pytest.mark.xfail(reason="v0.1: client_request_id not implemented yet, will be added in v0.2")
def test_agent_loop_idempotent_run_creation(temp_db, monkeypatch) -> None:
    """🔥 Priority 1: Test that duplicate Decision should not create duplicate Run.
    
    Scenario:
    - Same user message
    - Call _create_message twice
    - Both decisions are run-only
    
    Expected:
    - At most 1 run created
    - Second call either:
      - Doesn't create run, OR
      - Falls back to reply-only
    
    Note: This can be implemented via client_request_id or "recent run deduplication".
    Even if v0.1 marks this as xfail, it's worth writing the test to reserve the slot.
    """
    db, _ = temp_db
    
    # Create conversation
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # Mock Agent Decision to return run-only (same decision both times)
    def mock_decide(*args, **kwargs):
        from app.services.agent_decision import Decision, RunDecision
        return Decision(
            decision="run",
            reply=None,
            run=RunDecision(
                type="sleep",
                title="Sleep 5 seconds",
                conversation_id=conversation_id,
                input={"seconds": 5},
            ),
            confidence=0.95,
            reason="User wants to sleep",
        )
    
    # Enable Agent Loop and mock AgentDecision
    monkeypatch.setattr(conversations, "AGENT_LOOP_ENABLED", True)
    monkeypatch.setattr(conversations, "AGENT_DECISION_AVAILABLE", True)
    
    # Mock AgentDecision.decide directly
    with patch("app.api.conversations.AgentDecision") as mock_agent_decision_class:
        mock_agent_decision = MagicMock()
        mock_agent_decision.decide = MagicMock(side_effect=mock_decide)
        mock_agent_decision.get_active_facts = MagicMock(return_value=[])
        mock_agent_decision_class.return_value = mock_agent_decision
        
        # First call: Create message
        message_request = conversations.MessageCreateRequest(content="Sleep for 5 seconds")
        result1 = asyncio.run(conversations._create_message(conversation_id, message_request, db))
        _commit_db(db)
        
        # Second call: Same message again
        message_request2 = conversations.MessageCreateRequest(content="Sleep for 5 seconds")
        result2 = asyncio.run(conversations._create_message(conversation_id, message_request2, db))
        _commit_db(db)
    
    # Verify at most 1 run was created
    from app.api.runs import _list_conversation_runs
    runs_result = asyncio.run(_list_conversation_runs(conversation_id, db))
    assert len(runs_result["items"]) <= 1, "Should create at most 1 run for duplicate decisions"


def test_agent_loop_whitelist_fallback_reply_content(temp_db, monkeypatch) -> None:
    """🔥 Priority 2: Test that whitelist fallback includes explanation in reply content.
    
    When decision.run.type is not in whitelist:
    - Should fallback to reply-only
    - reply.content should contain explanation about unsupported task type
    - Should not silently swallow the issue (UX + Debug concern)
    """
    db, _ = temp_db
    
    # Create conversation
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # Mock LLM to return Decision with invalid run type
    # The whitelist check happens in AgentDecision.decide(), so we need to use real AgentDecision
    decision_json = {
        "decision": "run",
        "reply": None,
        "run": {
            "type": "invalid_task_type",
            "title": "Invalid task",
            "conversation_id": conversation_id,
            "input": {},
        },
        "confidence": 0.9,
        "reason": "Test",
    }
    
    class MockLLM:
        def __init__(self, response):
            self.response = response
        
        def generate(self, prompt: str) -> str:
            return self.response
    
    from agent_worker.llm.json_only import JsonOnlyLLMWrapper
    mock_llm = JsonOnlyLLMWrapper(MockLLM(json.dumps(decision_json)))
    
    # Enable Agent Loop
    monkeypatch.setattr(conversations, "AGENT_LOOP_ENABLED", True)
    monkeypatch.setattr(conversations, "AGENT_DECISION_AVAILABLE", True)
    
    # Use real AgentDecision so whitelist check happens
    with patch("app.api.conversations.AgentDecision") as mock_agent_decision_class:
        from app.services.agent_decision import AgentDecision
        
        agent_decision = AgentDecision()
        agent_decision._llm = mock_llm
        agent_decision._memory_client = MagicMock()
        agent_decision._memory_client.list_facts = MagicMock(return_value=[])
        
        mock_agent_decision_class.return_value = agent_decision
        
        # Create message
        message_request = conversations.MessageCreateRequest(content="Do something invalid")
        result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
        _commit_db(db)
    
    # Verify fallback to reply-only
    assert "user_message" in result
    assert "assistant_message" in result
    assert result["assistant_message"]["role"] == "assistant"
    
    # Verify reply content contains explanation about unsupported task type
    reply_content = result["assistant_message"]["content"]
    assert "不在允许列表中" in reply_content or "不允许" in reply_content or "不支持" in reply_content
    assert "invalid_task_type" in reply_content or "任务类型" in reply_content
    
    # Verify no run was created
    from app.api.runs import _list_conversation_runs
    runs_result = asyncio.run(_list_conversation_runs(conversation_id, db))
    assert len(runs_result["items"]) == 0


@pytest.mark.skip(reason="v0.1: notify flag not implemented yet, will be added in future version")
def test_agent_loop_run_only_without_notify(temp_db, monkeypatch) -> None:
    """🔥 Priority 3: Test run-only decision without notify flag.
    
    Should explicitly distinguish two cases:
    - decision=run and notify=false → No reply message
    - decision=run and notify=true → Write hint message
    
    Even if notify is not implemented now, we write a pending test.
    """
    db, _ = temp_db
    
    # Create conversation
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # This test will be implemented when notify flag is added
    # For now, we verify current behavior: run-only creates hint message
    def mock_decide(*args, **kwargs):
        from app.services.agent_decision import Decision, RunDecision
        return Decision(
            decision="run",
            reply=None,
            run=RunDecision(
                type="sleep",
                title="Sleep 5 seconds",
                conversation_id=conversation_id,
                input={"seconds": 5},
            ),
            confidence=0.95,
            reason="User wants to sleep",
        )
    
    monkeypatch.setattr(conversations, "AGENT_LOOP_ENABLED", True)
    monkeypatch.setattr(conversations, "AGENT_DECISION_AVAILABLE", True)
    
    with patch("app.api.conversations.AgentDecision") as mock_agent_decision_class:
        mock_agent_decision = MagicMock()
        mock_agent_decision.decide = MagicMock(side_effect=mock_decide)
        mock_agent_decision.get_active_facts = MagicMock(return_value=[])
        mock_agent_decision_class.return_value = mock_agent_decision
        
        message_request = conversations.MessageCreateRequest(content="Sleep")
        result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
        _commit_db(db)
    
    # Current behavior: creates hint message
    # Future: when notify=false, should not create reply message
    assert "assistant_message" in result
    # This assertion will change when notify flag is implemented


def test_agent_decision_prompt_includes_active_facts(temp_db, monkeypatch) -> None:
    """➕ Priority 4: Test that Decision prompt includes active facts (integration level).
    
    We tested get_active_facts, but didn't test:
    - Whether prompt actually contains these facts
    
    Can mock LLM and assert that the prompt contains:
    - memory key
    - value
    
    This is the foundation for Agent to "use memory".
    """
    db, _ = temp_db
    
    # Create conversation
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # Mock active facts
    active_facts = [
        {"key": "user_name", "value": "Alice"},
        {"key": "favorite_color", "value": "blue"},
    ]
    
    # Track the prompt that was passed to LLM
    captured_prompt = []
    
    class PromptCapturingLLM:
        """LLM that captures the prompt for inspection."""
        def __init__(self, response):
            self.response = response
        
        def generate(self, prompt: str) -> str:
            captured_prompt.append(prompt)
            return self.response
    
    # Mock LLM response
    decision_json = {
        "decision": "reply",
        "reply": {"content": "Hello!"},
        "run": None,
        "confidence": 0.9,
        "reason": "Test",
    }
    mock_llm = PromptCapturingLLM(json.dumps(decision_json))
    
    # Enable Agent Loop
    monkeypatch.setattr(conversations, "AGENT_LOOP_ENABLED", True)
    monkeypatch.setattr(conversations, "AGENT_DECISION_AVAILABLE", True)
    
    # Mock AgentDecision to capture prompt
    with patch("app.api.conversations.AgentDecision") as mock_agent_decision_class:
        from agent_worker.llm.json_only import JsonOnlyLLMWrapper
        from app.services.agent_decision import AgentDecision
        
        agent_decision = AgentDecision()
        agent_decision._llm = JsonOnlyLLMWrapper(mock_llm)
        agent_decision._memory_client = MagicMock()
        agent_decision._memory_client.list_facts = MagicMock(return_value=active_facts)
        
        mock_agent_decision_class.return_value = agent_decision
        
        # Create message
        message_request = conversations.MessageCreateRequest(content="Hello")
        result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
        _commit_db(db)
    
    # Verify prompt contains active facts
    assert len(captured_prompt) > 0, "Prompt should have been captured"
    prompt_text = captured_prompt[0]
    
    # Check that prompt contains memory keys/values
    assert "user_name" in prompt_text or "Alice" in prompt_text
    assert "favorite_color" in prompt_text or "blue" in prompt_text


def test_agent_decision_confidence_logging(temp_db, monkeypatch) -> None:
    """➕ Priority 5: Test that Decision confidence is logged consistently.
    
    If Decision returns confidence:
    - Is it completely ignored now?
    - Or is it logged?
    
    Suggest testing to clarify this, avoiding future inconsistent behavior.
    """
    db, _ = temp_db
    
    # Create conversation
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # Capture logs
    log_capture = StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.INFO)
    
    # Get logger and add handler
    logger = logging.getLogger("app.services.agent_decision")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    
    try:
        # Mock LLM to return Decision with high confidence
        # Use real AgentDecision so logging happens
        decision_json = {
            "decision": "reply",
            "reply": {"content": "High confidence reply"},
            "run": None,
            "confidence": 0.95,  # High confidence
            "reason": "Very certain",
        }
        
        class MockLLM:
            def __init__(self, response):
                self.response = response
            
            def generate(self, prompt: str) -> str:
                return self.response
        
        from agent_worker.llm.json_only import JsonOnlyLLMWrapper
        mock_llm = JsonOnlyLLMWrapper(MockLLM(json.dumps(decision_json)))
        
        # Enable Agent Loop
        monkeypatch.setattr(conversations, "AGENT_LOOP_ENABLED", True)
        monkeypatch.setattr(conversations, "AGENT_DECISION_AVAILABLE", True)
        
        # Use real AgentDecision so logging happens
        with patch("app.api.conversations.AgentDecision") as mock_agent_decision_class:
            from app.services.agent_decision import AgentDecision
            
            agent_decision = AgentDecision()
            agent_decision._llm = mock_llm
            agent_decision._memory_client = MagicMock()
            agent_decision._memory_client.list_facts = MagicMock(return_value=[])
            
            mock_agent_decision_class.return_value = agent_decision
            
            # Create message
            message_request = conversations.MessageCreateRequest(content="Test")
            result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
            _commit_db(db)
        
        # Verify confidence is logged
        log_output = log_capture.getvalue()
        # Current implementation logs confidence in decide() method
        assert "confidence" in log_output.lower() or "0.95" in log_output
        
    finally:
        logger.removeHandler(handler)


def test_agent_decision_invalid_reply_content_type(temp_db, monkeypatch) -> None:
    """➕ Priority 6: Test defense against invalid Decision output role/content.
    
    For example:
    {
      "decision": "reply",
      "reply": { "content": 123 }  // Should be string
    }
    
    Schema might catch this, but adding a test prevents future schema relaxation.
    """
    db, _ = temp_db
    
    # Create conversation
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # Mock LLM response with invalid content type (number instead of string)
    decision_json = {
        "decision": "reply",
        "reply": {"content": 123},  # Invalid: should be string
        "run": None,
        "confidence": 0.9,
        "reason": "Test",
    }
    
    class MockLLM:
        def __init__(self, response):
            self.response = response
        
        def generate(self, prompt: str) -> str:
            return self.response
    
    from agent_worker.llm.json_only import JsonOnlyLLMWrapper
    mock_llm = JsonOnlyLLMWrapper(MockLLM(json.dumps(decision_json)))
    
    # Enable Agent Loop
    monkeypatch.setattr(conversations, "AGENT_LOOP_ENABLED", True)
    monkeypatch.setattr(conversations, "AGENT_DECISION_AVAILABLE", True)
    
    # Mock AgentDecision with invalid response
    with patch("app.api.conversations.AgentDecision") as mock_agent_decision_class:
        from app.services.agent_decision import AgentDecision
        
        agent_decision = AgentDecision()
        agent_decision._llm = mock_llm
        agent_decision._memory_client = MagicMock()
        agent_decision._memory_client.list_facts = MagicMock(return_value=[])
        
        mock_agent_decision_class.return_value = agent_decision
        
        # Should fallback to chat_flow due to schema validation failure
        # (not raise exception, but fallback gracefully)
        message_request = conversations.MessageCreateRequest(content="Test")
        result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
        _commit_db(db)
        
        # Verify fallback happened (should use chat_flow, not Decision)
        assert "user_message" in result
        assert "assistant_message" in result
        # The message should come from chat_flow fallback, not Decision
        # (meta_json should NOT indicate agent_decision was used)
        assert result["assistant_message"]["meta_json"] is None or result["assistant_message"]["meta_json"].get("agent_decision") is not True
