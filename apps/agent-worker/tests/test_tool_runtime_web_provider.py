"""ToolRuntime + WebProvider 集成：step 可观测性、error_code。"""

from unittest.mock import Mock

import pytest

from worker.task_context import TaskContext
from worker.tools.catalog import ToolCatalog
from worker.tools.provider import BuiltinProvider, StubProvider
from worker.tools.runtime import ToolRuntime
from worker.tools.web_backends.errors import WebInvalidInputError
from worker.tools.web_backends.fetch_stub import StubWebFetchBackend
from worker.tools.web_backends.stub import StubWebSearchBackend
from worker.tools.web_provider import WebProvider


def test_tool_runtime_records_step_for_web_search_success():
    """Catalog 含 WebProvider 时，invoke web.search 产生 step tool.web.search，ok=True，meta 含 args_preview/result_preview。"""
    catalog = ToolCatalog(preferred_provider_order=["web", "builtin", "stub"])
    catalog.register_provider("web", WebProvider(
        search_backend=StubWebSearchBackend(),
        fetch_backend=StubWebFetchBackend(),
    ))
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("stub", StubProvider())
    runtime = ToolRuntime(catalog=catalog)
    run = Mock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")
    result = runtime.invoke(ctx, "web.search", {"query": "x"}, llm=None)
    assert isinstance(result, dict)
    assert "items" in result
    out = ctx.build_output()
    assert out.get("ok") is True
    steps = out.get("steps", [])
    names = [s["name"] for s in steps]
    assert "tool.web.search" in names
    step = next(s for s in steps if s["name"] == "tool.web.search")
    assert step["ok"] is True
    assert "args_preview" in step["meta"]
    assert "result_preview" in step["meta"]
    assert step["meta"].get("provider_id") == "web"


def test_tool_runtime_records_error_code_for_invalid_input():
    """invoke query='' 触发 InvalidInput；build_output 中 ok=False，step.error_code=InvalidInput，顶层 error.code=InvalidInput。"""
    catalog = ToolCatalog(preferred_provider_order=["web", "builtin", "stub"])
    catalog.register_provider("web", WebProvider(
        search_backend=StubWebSearchBackend(),
        fetch_backend=StubWebFetchBackend(),
    ))
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("stub", StubProvider())
    runtime = ToolRuntime(catalog=catalog)
    run = Mock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")
    with pytest.raises(WebInvalidInputError):
        runtime.invoke(ctx, "web.search", {"query": ""}, llm=None)
    out = ctx.build_output()
    assert out.get("ok") is False
    steps = out.get("steps", [])
    step = next((s for s in steps if s["name"] == "tool.web.search"), None)
    assert step is not None
    assert step["ok"] is False
    assert step.get("error_code") == "InvalidInput"
    assert out.get("error", {}).get("code") == "InvalidInput"
