"""Tests for research_report task: trace_id, steps, artifacts (stub)."""

from unittest.mock import Mock

import pytest

from worker.runner import TaskRunner
from worker.tools import ToolCatalog, ToolRuntime
from worker.tools.catalog import get_default_catalog


def test_research_report_output_has_trace_id_steps_and_task_type():
    """research_report 执行后 output 含 trace_id、steps、task_type、version。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"query": "test query", "trace_id": "a" * 32}
    result = runner._handle_research_report(run, lambda: True)
    assert result["trace_id"] == "a" * 32
    assert result.get("version") == "task_result_v0"
    assert result.get("task_type") == "research_report"
    assert "steps" in result
    names = [s["name"] for s in result["steps"]]
    assert names == ["tool.web.search", "tool.web.fetch", "extract", "dedupe_rank", "write_report"]
    for s in result["steps"]:
        assert s["duration_ms"] >= 0
        assert "ok" in s
        assert "error_code" in s
        assert "meta" in s


def test_research_report_output_has_artifacts_report_and_sources():
    """research_report 的 artifacts 含 report、sources；sources 项可有 provider。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"query": "stub"}
    result = runner._handle_research_report(run, lambda: True)
    assert result.get("ok") is True
    assert "artifacts" in result
    assert "report" in result["artifacts"]
    assert "text" in result["artifacts"]["report"]
    assert result["artifacts"]["report"].get("format") == "markdown"
    assert "sources" in result["artifacts"]
    sources = result["artifacts"]["sources"]
    assert isinstance(sources, list)
    for item in sources:
        assert "title" in item
        assert "url" in item
        assert "snippet" in item
        assert item.get("provider") in ("stub", "web", None)


def test_research_report_sources_have_provider_stub():
    """stub 下 sources 每项带 provider=stub。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"query": "x", "max_sources": 2}
    result = runner._handle_research_report(run, lambda: True)
    sources = result["artifacts"]["sources"]
    assert len(sources) >= 1
    for s in sources:
        assert s.get("provider") == "stub"


def test_research_report_tool_steps_have_args_preview_result_preview():
    """tool 步骤的 meta 含 args_preview、result_preview。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"query": "q"}
    result = runner._handle_research_report(run, lambda: True)
    steps = result["steps"]
    tool_steps = [s for s in steps if s["name"].startswith("tool.")]
    assert len(tool_steps) >= 2
    for s in tool_steps:
        assert "args_preview" in s.get("meta", {})
        assert "result_preview" in s.get("meta", {})


def test_research_report_optional_evidence():
    """artifacts 可有 evidence 列表。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"query": "q"}
    result = runner._handle_research_report(run, lambda: True)
    artifacts = result["artifacts"]
    if "evidence" in artifacts:
        for e in artifacts["evidence"]:
            assert "quote" in e or "source_index" in e


def test_research_report_invalid_query_raises():
    """query 缺失或非字符串时抛出 ValueError。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {}
    with pytest.raises(ValueError, match="query"):
        runner._handle_research_report(run, lambda: True)


def test_research_report_trace_lines_contain_trace_id():
    """trace_lines 中出现 trace_id。"""
    runner = TaskRunner()
    trace_id = "b" * 32
    run = Mock()
    run.input_json = {"query": "q", "trace_id": trace_id}
    result = runner._handle_research_report(run, lambda: True)
    assert "trace_lines" in result
    assert any(trace_id in line for line in result["trace_lines"])


def test_research_report_steps_order_stable():
    """steps 顺序固定，避免未来并行化后 UI 乱序。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"query": "q"}
    result = runner._handle_research_report(run, lambda: True)
    names = [s["name"] for s in result["steps"]]
    expected = ["tool.web.search", "tool.web.fetch", "extract", "dedupe_rank", "write_report"]
    assert names == expected


def test_research_report_tool_fetch_missing_returns_ok_false_tool_not_found():
    """工具调用失败路径可回放：取消注册 web.fetch 后触发 research_report，output.ok=false、error.code=ToolNotFound、steps 中 tool.web.fetch.ok=false、trace_lines 含 trace_id。"""
    catalog = ToolCatalog()
    meta = get_default_catalog().get("web.search")
    assert meta is not None
    catalog.register(meta)
    # web.fetch 不注册，触发 ToolNotFound
    runtime = ToolRuntime(catalog=catalog)
    runner = TaskRunner()
    trace_id = "c" * 32
    run = Mock()
    run.input_json = {"query": "x", "trace_id": trace_id}
    result = runner._handle_research_report(run, lambda: True, runtime=runtime)
    assert result.get("ok") is False
    assert result.get("error", {}).get("code") == "ToolNotFound"
    steps = result.get("steps", [])
    fetch_step = next((s for s in steps if s["name"] == "tool.web.fetch"), None)
    assert fetch_step is not None
    assert fetch_step.get("ok") is False
    assert fetch_step.get("error_code")
    assert "trace_lines" in result
    assert any(trace_id in line for line in result["trace_lines"])
