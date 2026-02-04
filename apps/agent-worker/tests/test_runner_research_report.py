"""Tests for research_report task: trace_id, steps, artifacts (stub)."""

from unittest.mock import Mock

import pytest

from worker.runner import TaskRunner
from worker.tools import ToolCatalog, ToolRuntime
from worker.tools.catalog import get_default_catalog


def test_research_report_output_has_trace_id_steps_and_task_type():
    """research_report 执行后 output 含 trace_id、steps、task_type、version；steps 含 1 个 search + N 个 fetch + extract + dedupe_rank + write_report。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"query": "test query", "trace_id": "a" * 32}
    result = runner._handle_research_report(run, lambda: True)
    assert result["trace_id"] == "a" * 32
    assert result.get("version") == "task_result_v0"
    assert result.get("task_type") == "research_report"
    assert "steps" in result
    names = [s["name"] for s in result["steps"]]
    assert names[0] == "tool.web.search"
    fetch_steps = [n for n in names if n == "tool.web.fetch"]
    assert len(fetch_steps) >= 1
    assert "extract" in names
    assert "dedupe_rank" in names
    assert "write_report" in names
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
    """artifacts 可有 evidence 列表，每条含 quote、source_url、source_index。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"query": "q"}
    result = runner._handle_research_report(run, lambda: True)
    artifacts = result["artifacts"]
    assert "evidence" in artifacts
    evidence = artifacts["evidence"]
    assert isinstance(evidence, list)
    for e in evidence:
        assert "quote" in e or "source_index" in e
        assert "source_url" in e
        assert "source_index" in e


def test_research_report_missing_query_uses_fallback():
    """query 缺失或非字符串时用 run.title 或 '调研' 兜底，不抛错。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {}
    run.title = None
    result = runner._handle_research_report(run, lambda: True)
    assert result.get("task_type") == "research_report"
    assert "artifacts" in result
    assert "report" in result["artifacts"]
    report_text = result["artifacts"]["report"].get("text", "")
    assert "调研" in report_text


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
    """steps 顺序：tool.web.search + N 个 tool.web.fetch + extract + dedupe_rank + write_report。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"query": "q"}
    result = runner._handle_research_report(run, lambda: True)
    names = [s["name"] for s in result["steps"]]
    assert names[0] == "tool.web.search"
    assert names[-3:] == ["extract", "dedupe_rank", "write_report"]
    fetch_count = sum(1 for n in names if n == "tool.web.fetch")
    assert fetch_count >= 1


def test_research_report_fetch_fills_content_per_url():
    """默认 catalog（stub search + stub fetch）：search 返回 2 个 URL，每个 URL 调 web.fetch，report 成功；fetch 步数等于 source 数。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"query": "x", "max_sources": 2}
    result = runner._handle_research_report(run, lambda: True)
    assert result.get("ok") is True
    steps = result.get("steps", [])
    fetch_steps = [s for s in steps if s["name"] == "tool.web.fetch"]
    assert len(fetch_steps) == 2
    assert all(s.get("ok") is True for s in fetch_steps)
    assert "artifacts" in result
    assert "sources" in result["artifacts"]
    assert len(result["artifacts"]["sources"]) == 2


def test_research_report_outputs_evidence_with_source_mapping():
    """extract 产出 artifacts.evidence，每条含 quote、source_url、source_index；至少 1 条且 source 映射正确。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"query": "q", "max_sources": 2}
    result = runner._handle_research_report(run, lambda: True)
    assert result.get("ok") is True
    evidence = result.get("artifacts", {}).get("evidence", [])
    assert len(evidence) >= 1
    sources = result.get("artifacts", {}).get("sources", [])
    for e in evidence:
        assert "quote" in e
        assert "source_url" in e
        assert "source_index" in e
        idx = e["source_index"]
        assert 0 <= idx < len(sources)
        assert e["source_url"] == sources[idx].get("url", "")


def test_research_report_tool_fetch_missing_returns_ok_false_tool_not_found():
    """工具调用失败路径可回放：仅注册 web.search、不提供 web.fetch，触发 ToolNotFound。"""
    from worker.tools.provider import SearchOnlyProvider

    catalog = ToolCatalog(preferred_provider_order=["search_only"])
    catalog.register_provider("search_only", SearchOnlyProvider())
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
