"""ToolRuntime + DDGHtmlBackend: step 可观测性、error_code 落 step。"""

import os
from unittest.mock import MagicMock, patch

import pytest

from worker.task_context import TaskContext
from worker.tools.catalog import ToolCatalog
from worker.tools.provider import BuiltinProvider, StubProvider
from worker.tools.runtime import ToolRuntime
from worker.tools.web_backends.ddg_html import DDGHtmlBackend
from worker.tools.web_backends.errors import WebBlockedError
from worker.tools.web_backends.fetch_stub import StubWebFetchBackend
from worker.tools.web_provider import WebProvider

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures", "ddg_html")


def _load_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_tool_runtime_web_search_ddg_success_records_step():
    """Catalog 含 WebProvider(DDGHtmlBackend)；mock HTTP 返回 fixture；invoke web.search → step ok=True，result_preview 非空。"""
    html = _load_fixture("results_basic.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    catalog = ToolCatalog(preferred_provider_order=["web", "builtin", "stub"])
    catalog.register_provider(
        "web",
        WebProvider(search_backend=DDGHtmlBackend(), fetch_backend=StubWebFetchBackend()),
    )
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("stub", StubProvider())
    runtime = ToolRuntime(catalog=catalog)
    run = MagicMock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")

    with patch("worker.tools.web_backends.ddg_html.httpx.Client", return_value=mock_client):
        result = runtime.invoke(ctx, "web.search", {"query": "x", "max_results": 2}, llm=None)
    assert isinstance(result, dict)
    assert "items" in result
    assert len(result["items"]) == 2
    out = ctx.build_output()
    assert out.get("ok") is True
    steps = out.get("steps", [])
    step = next((s for s in steps if s["name"] == "tool.web.search"), None)
    assert step is not None
    assert step["ok"] is True
    assert step["meta"].get("provider_id") == "web"
    assert step["meta"].get("result_preview")


def test_tool_runtime_web_search_ddg_blocked_sets_error_code():
    """Mock 403 → invoke 抛 → build_output ok=False，step.error_code==WebBlocked，顶层 error.code==WebBlocked。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = ""
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    catalog = ToolCatalog(preferred_provider_order=["web", "builtin", "stub"])
    catalog.register_provider(
        "web",
        WebProvider(search_backend=DDGHtmlBackend(), fetch_backend=StubWebFetchBackend()),
    )
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("stub", StubProvider())
    runtime = ToolRuntime(catalog=catalog)
    run = MagicMock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")

    with patch("worker.tools.web_backends.ddg_html.httpx.Client", return_value=mock_client):
        with pytest.raises(WebBlockedError):
            runtime.invoke(ctx, "web.search", {"query": "x"}, llm=None)
    out = ctx.build_output()
    assert out.get("ok") is False
    steps = out.get("steps", [])
    step = next((s for s in steps if s["name"] == "tool.web.search"), None)
    assert step is not None
    assert step["ok"] is False
    assert step.get("error_code") == "WebBlocked"
    assert out.get("error", {}).get("code") == "WebBlocked"
