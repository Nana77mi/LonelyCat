"""ToolRuntime + web.fetch: step 可观测性、error_code 落 step。"""

from unittest.mock import MagicMock

import pytest

from worker.task_context import TaskContext
from worker.tools.catalog import ToolCatalog
from worker.tools.provider import BuiltinProvider, StubProvider
from worker.tools.runtime import ToolRuntime
from worker.tools.web_backends.errors import WebBlockedError
from worker.tools.web_backends.fetch_stub import StubWebFetchBackend
from worker.tools.web_backends.stub import StubWebSearchBackend
from worker.tools.web_provider import WebProvider


def test_tool_runtime_web_fetch_success_records_step():
    """WebProvider(stub fetch) invoke web.fetch → step ok=True，meta 有 result_preview。"""
    catalog = ToolCatalog(preferred_provider_order=["web", "builtin", "stub"])
    catalog.register_provider(
        "web",
        WebProvider(
            search_backend=StubWebSearchBackend(),
            fetch_backend=StubWebFetchBackend(),
        ),
    )
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("stub", StubProvider())
    runtime = ToolRuntime(catalog=catalog)
    run = MagicMock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")
    result = runtime.invoke(ctx, "web.fetch", {"url": "https://example.com/a"}, llm=None)
    assert "url" in result and "text" in result
    out = ctx.build_output()
    assert out.get("ok") is True
    steps = out.get("steps", [])
    step = next((s for s in steps if s["name"] == "tool.web.fetch"), None)
    assert step is not None
    assert step["ok"] is True
    assert step["meta"].get("provider_id") == "web"
    assert step["meta"].get("result_preview")


def test_tool_runtime_web_fetch_blocked_sets_error_code_web_blocked():
    """Mock fetch backend 抛 WebBlockedError → step.error_code=WebBlocked，顶层 error.code=WebBlocked。"""
    class BlockingBackend:
        backend_id = "block"

        def fetch(self, url, timeout_ms):
            raise WebBlockedError("blocked")

    catalog = ToolCatalog(preferred_provider_order=["web", "builtin", "stub"])
    catalog.register_provider(
        "web",
        WebProvider(
            search_backend=StubWebSearchBackend(),
            fetch_backend=BlockingBackend(),
        ),
    )
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("stub", StubProvider())
    runtime = ToolRuntime(catalog=catalog)
    run = MagicMock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")
    with pytest.raises(WebBlockedError):
        runtime.invoke(ctx, "web.fetch", {"url": "https://example.com"}, llm=None)
    out = ctx.build_output()
    assert out.get("ok") is False
    steps = out.get("steps", [])
    step = next((s for s in steps if s["name"] == "tool.web.fetch"), None)
    assert step is not None
    assert step["ok"] is False
    assert step.get("error_code") == "WebBlocked"
    assert out.get("error", {}).get("code") == "WebBlocked"
