"""Tests for summarize_conversation: trace_id, steps, artifacts."""

import re
from unittest.mock import Mock

import pytest

from agent_worker.llm.stub import StubLLM
from worker.db_models import MessageRole
from worker.runner import TaskRunner


def _make_mock_db_with_messages(messages_list):
    """Return a Mock db where query(MessageModel).filter().filter().order_by().limit().all() returns messages_list."""
    db = Mock()
    chain = db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value
    chain.all.return_value = messages_list
    return db


def test_summarize_output_has_trace_id_steps_and_trace_lines():
    """summarize 执行后 output 含 trace_id、steps、trace_lines，且 trace_lines 中出现该 trace_id。"""
    runner = TaskRunner()
    runner._build_memory_client = lambda: None
    trace_id = "a" * 32
    run = Mock()
    run.input_json = {
        "conversation_id": "conv-1",
        "trace_id": trace_id,
        "max_messages": 20,
    }
    msg1 = Mock()
    msg1.role = MessageRole.USER
    msg1.content = "hi"
    msg2 = Mock()
    msg2.role = MessageRole.ASSISTANT
    msg2.content = "hello"
    db = _make_mock_db_with_messages([msg1, msg2])
    llm = StubLLM()
    result = runner._handle_summarize_conversation(run, db, llm, lambda: True)
    assert result["trace_id"] == trace_id
    assert "steps" in result
    names = [s["name"] for s in result["steps"]]
    assert names == ["fetch_messages", "fetch_facts", "build_prompt", "llm_generate"]
    for s in result["steps"]:
        assert s["duration_ms"] >= 0
        assert "ok" in s
        assert "error_code" in s
        assert "meta" in s
    assert "trace_lines" in result
    assert any(f"trace_id={trace_id}" in line for line in result["trace_lines"])


def test_summarize_output_trace_id_equals_input_when_provided():
    """input_json 提供合法 trace_id 时，output trace_id 与之一致。"""
    runner = TaskRunner()
    runner._build_memory_client = lambda: None
    trace_id = "b" * 32
    run = Mock()
    run.input_json = {"conversation_id": "c1", "trace_id": trace_id, "max_messages": 20}
    msg = Mock(role=MessageRole.USER, content="x")
    db = _make_mock_db_with_messages([msg])
    result = runner._handle_summarize_conversation(run, db, StubLLM(), lambda: True)
    assert result["trace_id"] == trace_id


def test_summarize_output_has_artifacts_and_steps_schema():
    """output 含 artifacts (summary + facts)，steps 含 name/duration_ms/ok/error_code/meta。"""
    runner = TaskRunner()
    runner._build_memory_client = lambda: None
    run = Mock()
    run.input_json = {"conversation_id": "c1", "max_messages": 20}
    msg = Mock(role=MessageRole.USER, content="test")
    db = _make_mock_db_with_messages([msg])
    result = runner._handle_summarize_conversation(run, db, StubLLM(), lambda: True)
    assert "artifacts" in result
    assert "summary" in result["artifacts"]
    assert "text" in result["artifacts"]["summary"]
    assert result["artifacts"]["summary"].get("format") == "markdown"
    assert "facts" in result["artifacts"]
    assert "snapshot_id" in result["artifacts"]["facts"]
    assert "source" in result["artifacts"]["facts"]
    assert re.match(r"^[a-f0-9]{64}$", result["artifacts"]["facts"]["snapshot_id"])
    for step in result["steps"]:
        assert "name" in step
        assert "duration_ms" in step
        assert step["duration_ms"] >= 0
        assert "ok" in step
        assert "error_code" in step
        assert "meta" in step


def test_summarize_llm_failure_has_llm_generate_ok_false_and_error_code():
    """Mock LLM 抛出异常时，output 中 llm_generate.ok==false 且 error_code 有值。"""
    runner = TaskRunner()
    runner._build_memory_client = lambda: None
    run = Mock()
    run.input_json = {"conversation_id": "c1", "trace_id": "c" * 32, "max_messages": 20}
    msg = Mock(role=MessageRole.USER, content="x")
    db = _make_mock_db_with_messages([msg])
    failing_llm = Mock()
    failing_llm.generate = Mock(side_effect=RuntimeError("mock_llm_error"))
    result = runner._handle_summarize_conversation(run, db, failing_llm, lambda: True)
    assert result.get("ok") is False
    assert "error" in result
    steps = result["steps"]
    llm_step = next(s for s in steps if s["name"] == "llm_generate")
    assert llm_step["ok"] is False
    assert llm_step["error_code"] is not None
    assert llm_step["error_code"] == "RuntimeError"
