"""Default catalog 按 WEB_SEARCH_BACKEND 选择 backend（stub/ddg_html/searxng/未知回退）。"""

import os
from unittest.mock import MagicMock, patch

import pytest

from worker.tools.catalog import _default_catalog_factory, _web_search_backend_from_env


def test_default_catalog_backend_stub_when_unset():
    """WEB_SEARCH_BACKEND 未设置或为空 → backend_id == stub。"""
    with patch.dict(os.environ, {"WEB_SEARCH_BACKEND": ""}, clear=False):
        backend = _web_search_backend_from_env()
    assert getattr(backend, "backend_id", None) == "stub"


def test_default_catalog_backend_ddg_html_when_set():
    """WEB_SEARCH_BACKEND=ddg_html → backend_id == ddg_html。"""
    with patch.dict(os.environ, {"WEB_SEARCH_BACKEND": "ddg_html"}, clear=False):
        backend = _web_search_backend_from_env()
    assert getattr(backend, "backend_id", None) == "ddg_html"


def test_default_catalog_backend_searxng_when_set():
    """WEB_SEARCH_BACKEND=searxng + SEARXNG_BASE_URL=http://x → backend_id == searxng。"""
    with patch.dict(
        os.environ,
        {"WEB_SEARCH_BACKEND": "searxng", "SEARXNG_BASE_URL": "http://x"},
        clear=False,
    ):
        backend = _web_search_backend_from_env()
    assert getattr(backend, "backend_id", None) == "searxng"


def test_default_catalog_backend_searxng_without_base_url_falls_back_to_stub():
    """WEB_SEARCH_BACKEND=searxng 但 SEARXNG_BASE_URL 未设置或为空 → 回退 stub。"""
    with patch.dict(
        os.environ,
        {"WEB_SEARCH_BACKEND": "searxng", "SEARXNG_BASE_URL": ""},
        clear=False,
    ):
        backend = _web_search_backend_from_env()
    assert getattr(backend, "backend_id", None) == "stub"


def test_default_catalog_backend_unknown_falls_back_to_stub_and_warns():
    """WEB_SEARCH_BACKEND=weird → 回退 stub 且 logger.warning 被调用。"""
    with patch.dict(os.environ, {"WEB_SEARCH_BACKEND": "weird"}, clear=False):
        with patch("worker.tools.catalog.logger") as mock_logger:
            backend = _web_search_backend_from_env()
    assert getattr(backend, "backend_id", None) == "stub"
    mock_logger.warning.assert_called()
    call_args = mock_logger.warning.call_args[0]
    assert "weird" in str(call_args) or "unknown" in str(call_args).lower()


def test_default_catalog_factory_stub_invokes_web_search():
    """未设置 WEB_SEARCH_BACKEND（或为 stub）时 catalog 的 web.search 返回 stub 结果。"""
    with patch.dict(os.environ, {"WEB_SEARCH_BACKEND": "stub"}, clear=False):
        catalog = _default_catalog_factory()
    from worker.task_context import TaskContext
    from worker.tools.runtime import ToolRuntime

    meta = catalog.get("web.search")
    assert meta is not None
    assert meta.provider_id == "web"
    run = MagicMock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")
    runtime = ToolRuntime(catalog=catalog)
    result = runtime.invoke(ctx, "web.search", {"query": "x", "max_results": 2}, llm=None)
    assert "items" in result
    assert len(result["items"]) >= 1
    assert result["items"][0].get("provider") == "stub"
    catalog.close_providers()
