"""DDGHtmlBackend tests: mock HTTP, no network."""

import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from worker.tools.web_backends.ddg_html import DDGHtmlBackend
from worker.tools.web_backends.errors import (
    WebBlockedError,
    WebNetworkError,
    WebParseError,
    WebTimeoutError,
)

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures", "ddg_html")


def _load_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_ddg_backend_search_returns_items_and_respects_max_results():
    """Mock 返回 results_basic.html；max_results=2 → 返回 2 条 dict，含 title/url/snippet。"""
    html = _load_fixture("results_basic.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.ddg_html.httpx.Client", return_value=mock_client):
        backend = DDGHtmlBackend()
        items = backend.search("test", max_results=2, timeout_ms=5000)
    assert len(items) == 2
    for it in items:
        assert "title" in it and "url" in it and "snippet" in it
    assert items[0]["title"] == "First Result Title"
    assert "example.com" in items[0]["url"]


def test_ddg_backend_http_403_raises_web_blocked():
    """Mock status=403 或 body 含 captcha → 抛 WebBlockedError 且 code==WebBlocked。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = ""
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.ddg_html.httpx.Client", return_value=mock_client):
        backend = DDGHtmlBackend()
        with pytest.raises(WebBlockedError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebBlocked"


def test_ddg_backend_body_captcha_raises_web_blocked():
    """Body 含 captcha → WebBlockedError。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "Please complete the captcha to continue."
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.ddg_html.httpx.Client", return_value=mock_client):
        backend = DDGHtmlBackend()
        with pytest.raises(WebBlockedError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebBlocked"


def test_ddg_backend_timeout_raises_timeout():
    """Mock 抛 TimeoutException → WebTimeoutError code Timeout。"""
    mock_client = MagicMock()
    mock_client.get.side_effect = httpx.TimeoutException("timed out")
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.ddg_html.httpx.Client", return_value=mock_client):
        backend = DDGHtmlBackend()
        with pytest.raises(WebTimeoutError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "Timeout"


def test_ddg_backend_parse_empty_raises_parse_error_when_not_no_results():
    """返回非 no_results 但解析不到结果的 HTML → WebParseError。"""
    html = _load_fixture("empty_parse.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.ddg_html.httpx.Client", return_value=mock_client):
        backend = DDGHtmlBackend()
        with pytest.raises(WebParseError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebParseError"


def test_ddg_backend_status_200_body_captcha_raises_web_blocked():
    """status=200 但 body 含 blocked 关键词（如 captcha）→ WebBlockedError。"""
    html = _load_fixture("blocked_keyword_only.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.ddg_html.httpx.Client", return_value=mock_client):
        backend = DDGHtmlBackend()
        with pytest.raises(WebBlockedError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebBlocked"


def test_ddg_backend_connect_error_raises_web_network_error():
    """Mock httpx.ConnectError / RequestError → WebNetworkError(code=NetworkError)。"""
    mock_client = MagicMock()
    mock_client.get.side_effect = httpx.ConnectError("connection refused")
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.ddg_html.httpx.Client", return_value=mock_client):
        backend = DDGHtmlBackend()
        with pytest.raises(WebNetworkError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "NetworkError"
