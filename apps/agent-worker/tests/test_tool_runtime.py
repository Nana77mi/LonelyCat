"""Tests for ToolCatalog and ToolRuntime: args/result preview, step name tool.{name}."""

import os
from unittest.mock import Mock

import pytest

from worker.task_context import TaskContext
from worker.tools import ToolCatalog, ToolMeta, ToolRuntime
from worker.tools.catalog import get_default_catalog
from worker.tools.runtime import ToolNotFoundError, _preview


def test_catalog_get_and_list(monkeypatch):
    """默认 catalog 含 WebProvider，web.search 由 web 提供；list_tools 含 web.search/web.fetch/text.summarize。"""
    monkeypatch.setenv("SKILLS_LIST_FALLBACK", "1")  # CI 无 core-api 时 SkillsProvider 返回占位不抛错
    catalog = get_default_catalog()
    meta = catalog.get("web.search")
    assert meta is not None
    assert meta.name == "web.search"
    assert meta.risk_level == "read_only"
    assert meta.side_effects is False
    assert meta.provider_id == "web"
    assert meta.capability_level == "L0"
    all_ = catalog.list_builtin()
    names = [m.name for m in all_]
    assert "web.search" in names
    assert "web.fetch" in names
    assert "text.summarize" in names


def test_preferred_provider_order_changes_tool_source():
    """切换 preferred_provider_order 后，同名工具解析自不同 provider（Phase 2.1）。"""
    from worker.tools.provider import BuiltinProvider, StubProvider

    catalog = ToolCatalog(preferred_provider_order=["builtin", "stub"])
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("stub", StubProvider())
    meta_builtin_first = catalog.get("web.search")
    assert meta_builtin_first is not None
    assert meta_builtin_first.provider_id == "builtin"

    catalog.set_preferred_provider_order(["stub", "builtin"])
    meta_stub_first = catalog.get("web.search")
    assert meta_stub_first is not None
    assert meta_stub_first.provider_id == "stub"


def test_runtime_invoke_creates_step_with_previews():
    """默认 catalog 含 WebProvider 时 web.search 返回 {"items": [...]}；step 含 args_preview/result_preview。"""
    run = Mock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")
    runtime = ToolRuntime()
    result = runtime.invoke(ctx, "web.search", {"query": "test"})
    items = result.get("items", result) if isinstance(result, dict) else result
    assert isinstance(items, list)
    assert len(items) >= 1
    steps = ctx._steps
    assert len(steps) == 1
    assert steps[0]["name"] == "tool.web.search"
    assert steps[0]["ok"] is True
    assert "args_preview" in steps[0]["meta"]
    assert "result_preview" in steps[0]["meta"]
    assert "test" in steps[0]["meta"]["args_preview"] or "query" in steps[0]["meta"]["args_preview"]
    assert steps[0]["meta"].get("provider_id") == "web"


def test_runtime_invoke_web_fetch():
    """默认 catalog 下 web.fetch 单 url 返回 canonical 形状（url/status_code/text/truncated）。"""
    run = Mock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")
    runtime = ToolRuntime()
    result = runtime.invoke(ctx, "web.fetch", {"url": "https://a.com"})
    assert isinstance(result, dict)
    assert "url" in result and "status_code" in result and "text" in result and "truncated" in result
    assert result["url"] == "https://a.com"
    steps = ctx._steps
    assert len(steps) == 1
    assert steps[0]["name"] == "tool.web.fetch"
    assert steps[0]["meta"].get("risk_level") == "read_only"


def test_runtime_unknown_tool_raises_tool_not_found_error(monkeypatch):
    """Tool 不存在时抛出 ToolNotFoundError，error.code 稳定。"""
    monkeypatch.setenv("SKILLS_LIST_FALLBACK", "1")  # CI 无 core-api 时 catalog.get/list_tools 不因 SkillsProvider 抛错
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
