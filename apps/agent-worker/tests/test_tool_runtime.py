"""Tests for ToolCatalog and ToolRuntime: args/result preview, step name tool.{name}."""

from unittest.mock import Mock

import pytest

from worker.task_context import TaskContext
from worker.tools import ToolCatalog, ToolMeta, ToolRuntime
from worker.tools.catalog import get_default_catalog
from worker.tools.runtime import ToolNotFoundError, _preview


def test_catalog_get_and_list():
    catalog = get_default_catalog()
    meta = catalog.get("web.search")
    assert meta is not None
    assert meta.name == "web.search"
    assert meta.risk_level == "read_only"
    assert meta.side_effects is False
    all_ = catalog.list_builtin()
    names = [m.name for m in all_]
    assert "web.search" in names
    assert "web.fetch" in names
    assert "text.summarize" in names


def test_runtime_invoke_creates_step_with_previews():
    run = Mock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")
    runtime = ToolRuntime()
    result = runtime.invoke(ctx, "web.search", {"query": "test"})
    assert isinstance(result, list)
    assert len(result) >= 1
    steps = ctx._steps
    assert len(steps) == 1
    assert steps[0]["name"] == "tool.web.search"
    assert steps[0]["ok"] is True
    assert "args_preview" in steps[0]["meta"]
    assert "result_preview" in steps[0]["meta"]
    assert "test" in steps[0]["meta"]["args_preview"] or "query" in steps[0]["meta"]["args_preview"]


def test_runtime_invoke_web_fetch():
    run = Mock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")
    runtime = ToolRuntime()
    result = runtime.invoke(ctx, "web.fetch", {"urls": ["https://a.com"]})
    assert "contents" in result
    assert "https://a.com" in result["contents"]
    steps = ctx._steps
    assert len(steps) == 1
    assert steps[0]["name"] == "tool.web.fetch"
    assert steps[0]["meta"].get("risk_level") == "read_only"


def test_runtime_unknown_tool_raises_tool_not_found_error():
    """Tool 不存在时抛出 ToolNotFoundError，error.code 稳定。"""
    run = Mock()
    run.input_json = {}
    ctx = TaskContext(run, "test")
    runtime = ToolRuntime()
    with pytest.raises(ToolNotFoundError, match="Tool not found"):
        runtime.invoke(ctx, "unknown.tool", {})


def test_preview_never_raises():
    """_preview 对任意对象不抛异常，返回可显示字符串。"""
    assert _preview(None) == ""
    assert _preview("ok") == "ok"
    assert _preview(123) == "123"
    assert _preview({"a": 1}, limit=5) in ('{"a":…', '{"a":1}')
    _preview(object())
    _preview({"x": object()}, limit=50)
