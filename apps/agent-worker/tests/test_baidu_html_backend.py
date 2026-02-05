"""BaiduHtmlSearchBackend tests: mock HTTP, no network. 403/429 用 status_code 判定。"""

import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from worker.tools.web_backends.baidu_html import BaiduHtmlSearchBackend
from worker.tools.web_backends.errors import (
    WebBlockedError,
    WebNetworkError,
    WebTimeoutError,
)

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures", "baidu_html")


def _load_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_baidu_backend_search_returns_items_and_respects_max_results():
    """Mock 200 + results_basic.html；max_results=2 → 返回 2 条，含 title/url/snippet。"""
    html = _load_fixture("results_basic.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend(timeout_ms=5000)
        items = backend.search("test", max_results=2, timeout_ms=5000)
    assert len(items) == 2
    for it in items:
        assert "title" in it and "url" in it and "snippet" in it
    assert items[0]["title"] == "First Result Title"
    assert "example.com" in items[0]["url"]


def test_baidu_backend_http_403_raises_web_blocked_detail_code_http_403():
    """Mock status_code=403 → WebBlockedError，detail_code=http_403。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = ""
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        with pytest.raises(WebBlockedError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebBlocked"
    assert getattr(exc_info.value, "detail_code", None) == "http_403"


def test_baidu_backend_http_429_raises_web_blocked_detail_code_http_429():
    """Mock status_code=429 → WebBlockedError，detail_code=http_429。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = ""
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        with pytest.raises(WebBlockedError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebBlocked"
    assert getattr(exc_info.value, "detail_code", None) == "http_429"


def test_baidu_backend_captcha_html_raises_web_blocked_detail_code_captcha_required():
    """Mock 200 + blocked_captcha.html（验证码关键词）→ WebBlockedError，detail_code=captcha_required。"""
    html = _load_fixture("blocked_captcha.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        with pytest.raises(WebBlockedError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebBlocked"
    assert getattr(exc_info.value, "detail_code", None) == "captcha_required"


def test_baidu_backend_timeout_raises_timeout():
    """Mock TimeoutException → WebTimeoutError。"""
    mock_client = MagicMock()
    mock_client.get.side_effect = httpx.TimeoutException("timed out")
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        with pytest.raises(WebTimeoutError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "Timeout"


def test_baidu_backend_request_error_raises_network_error():
    """Mock RequestError → WebNetworkError。"""
    mock_client = MagicMock()
    mock_client.get.side_effect = httpx.RequestError("connection failed")
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        with pytest.raises(WebNetworkError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "NetworkError"


def test_baidu_backend_query_encoded_in_url():
    """search 调用时 URL 含编码后的 query。"""
    html = _load_fixture("results_basic.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        backend.search("hello world", max_results=5, timeout_ms=5000)
    call_args = mock_client.get.call_args
    assert call_args is not None
    url = call_args[0][0] if call_args[0] else call_args[1].get("url")
    assert url is not None
    assert "wd=" in url
    assert "hello" in url or "hello%20world" in url or "hello+world" in url
