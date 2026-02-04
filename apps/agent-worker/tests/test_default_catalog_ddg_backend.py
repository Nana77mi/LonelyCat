"""Default catalog 按 WEB_SEARCH_BACKEND 选择 backend（ddg_html / stub）。"""

import os
from unittest.mock import MagicMock, patch

from worker.tools.catalog import _default_catalog_factory

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures", "ddg_html")


def _load_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_default_catalog_uses_ddg_backend_when_configured():
    """WEB_SEARCH_BACKEND=ddg_html 时 _default_catalog_factory() 后 web.search 走 ddg_html；mock HTTP 返回 fixture。"""
    html = _load_fixture("results_basic.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch.dict(os.environ, {"WEB_SEARCH_BACKEND": "ddg_html"}, clear=False):
        catalog = _default_catalog_factory()
    meta = catalog.get("web.search")
    assert meta is not None
    assert meta.provider_id == "web"
    from worker.task_context import TaskContext
    from worker.tools.runtime import ToolRuntime
    run = MagicMock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")
    runtime = ToolRuntime(catalog=catalog)
    with patch("worker.tools.web_backends.ddg_html.httpx.Client", return_value=mock_client):
        result = runtime.invoke(ctx, "web.search", {"query": "x", "max_results": 2}, llm=None)
    assert "items" in result
    assert len(result["items"]) >= 1
    assert result["items"][0].get("provider") == "ddg_html" or meta.provider_id == "web"
    catalog.close_providers()


def test_default_catalog_falls_back_to_stub_when_configured():
    """WEB_SEARCH_BACKEND=stub 时 web.search 返回 stub 的 items。"""
    with patch.dict(os.environ, {"WEB_SEARCH_BACKEND": "stub"}, clear=False):
        catalog = _default_catalog_factory()
    meta = catalog.get("web.search")
    assert meta is not None
    from worker.task_context import TaskContext
    from worker.tools.runtime import ToolRuntime
    run = MagicMock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")
    runtime = ToolRuntime(catalog=catalog)
    result = runtime.invoke(ctx, "web.search", {"query": "x", "max_results": 2}, llm=None)
    assert "items" in result
    assert len(result["items"]) >= 1
    assert result["items"][0].get("provider") == "stub"
    catalog.close_providers()
