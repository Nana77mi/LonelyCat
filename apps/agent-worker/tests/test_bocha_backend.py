"""BochaBackend tests: mock httpx (client.post), no network."""

import json
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from worker.tools.web_backends.errors import (
    WebAuthError,
    WebBadGatewayError,
    WebBlockedError,
    WebNetworkError,
    WebParseError,
    WebTimeoutError,
)
from worker.tools.web_backends.bocha import BochaBackend

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures", "bocha")


def _load_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_bocha_backend_200_returns_items_and_respects_max_results():
    """Mock httpx 返回 results_basic.json；max_results=2 → 返回 2 条，provider=bocha。"""
    raw = _load_fixture("results_basic.json")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = json.loads(raw)
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.bocha.httpx.Client", return_value=mock_client):
        backend = BochaBackend(api_key="test-key")
        result = backend.search("test", max_results=2, timeout_ms=5000)
    items = result.get("items", [])
    assert len(items) == 2
    for it in items:
        assert "title" in it and "url" in it and "snippet" in it
        assert it.get("provider") == "bocha"
    assert items[0]["title"] == "First Result Title"
    assert "example.com/first" in items[0]["url"]
    mock_client.post.assert_called_once()
    call_kw = mock_client.post.call_args[1]
    assert call_kw.get("json", {}).get("query") == "test"
    assert call_kw.get("json", {}).get("count") == 2


def test_bocha_backend_no_api_key_raises_auth_error():
    """无 api_key → WebAuthError。"""
    backend = BochaBackend(api_key="")
    with pytest.raises(WebAuthError) as exc_info:
        backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "AuthError"


def test_bocha_backend_remaining_budget_zero_skips_and_returns_empty():
    """remaining_budget_ms<=0 时跳过请求，返回 { items: [] }，不打 HTTP。"""
    backend = BochaBackend(api_key="key")
    result = backend.search(
        "q", max_results=5, timeout_ms=5000, remaining_budget_ms=0
    )
    assert isinstance(result, dict)
    assert result.get("items") == []


def test_bocha_backend_401_raises_auth_error():
    """Mock 401 → WebAuthError code AuthError。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.bocha.httpx.Client", return_value=mock_client):
        backend = BochaBackend(api_key="key")
        with pytest.raises(WebAuthError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "AuthError"


def test_bocha_backend_403_raises_auth_error():
    """Mock 403 → WebAuthError。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.bocha.httpx.Client", return_value=mock_client):
        backend = BochaBackend(api_key="key")
        with pytest.raises(WebAuthError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "AuthError"


def test_bocha_backend_429_raises_web_blocked():
    """Mock 429 → WebBlockedError detail_code=http_429。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.bocha.httpx.Client", return_value=mock_client):
        backend = BochaBackend(api_key="key")
        with pytest.raises(WebBlockedError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebBlocked"
    assert exc_info.value.detail_code == "http_429"


def test_bocha_backend_5xx_raises_bad_gateway():
    """Mock 5xx → WebBadGatewayError code BadGateway。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 502
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.bocha.httpx.Client", return_value=mock_client):
        backend = BochaBackend(api_key="key")
        with pytest.raises(WebBadGatewayError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "BadGateway"


def test_bocha_backend_timeout_raises_web_timeout():
    """Mock timeout → WebTimeoutError code Timeout。"""
    with patch("worker.tools.web_backends.bocha.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.TimeoutException("timeout")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client
        backend = BochaBackend(api_key="key")
        with pytest.raises(WebTimeoutError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "Timeout"


def test_bocha_backend_network_error_raises_web_network_error():
    """Mock httpx.RequestError → WebNetworkError。"""
    with patch("worker.tools.web_backends.bocha.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectError("connection refused")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client
        backend = BochaBackend(api_key="key")
        with pytest.raises(WebNetworkError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "NetworkError"


def test_bocha_backend_empty_results_raises_parse_error():
    """Mock results_empty.json → WebParseError EmptyResult。"""
    raw = _load_fixture("results_empty.json")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = json.loads(raw)
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.bocha.httpx.Client", return_value=mock_client):
        backend = BochaBackend(api_key="key")
        with pytest.raises(WebParseError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebParseError"
    assert "EmptyResult" in str(exc_info.value)


def test_bocha_backend_malformed_response_raises_parse_error():
    """返回 results_malformed.json 或缺字段 → WebParseError。"""
    raw = _load_fixture("results_malformed.json")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = json.loads(raw)
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.bocha.httpx.Client", return_value=mock_client):
        backend = BochaBackend(api_key="key")
        with pytest.raises(WebParseError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebParseError"


def test_bocha_backend_json_decode_error_raises_parse_error():
    """Mock resp.json() 抛 ValueError → WebParseError。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = ValueError("Expecting value")
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.bocha.httpx.Client", return_value=mock_client):
        backend = BochaBackend(api_key="key")
        with pytest.raises(WebParseError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebParseError"


def test_bocha_backend_filters_non_http_urls():
    """只保留 http(s) URL；非 http 的项被丢弃。"""
    raw = json.dumps({
        "results": [
            {"title": "OK", "url": "https://example.com/a", "snippet": "x"},
            {"title": "Skip", "url": "ftp://example.com/b", "snippet": "y"},
            {"title": "OK2", "url": "http://example.com/c", "snippet": "z"},
        ]
    })
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = json.loads(raw)
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.bocha.httpx.Client", return_value=mock_client):
        backend = BochaBackend(api_key="key")
        result = backend.search("q", max_results=5, timeout_ms=5000)
    items = result.get("items", [])
    assert len(items) == 2
    urls = [it["url"] for it in items]
    assert "https://example.com/a" in urls
    assert "http://example.com/c" in urls
    assert "ftp://example.com/b" not in urls


def test_bocha_backend_webpages_value_official_bing_compat():
    """官方 Bing 兼容结构 webPages.value：name->title, url, snippet, datePublished, siteName/siteIcon->meta。"""
    raw = _load_fixture("webpages_value_official.json")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = json.loads(raw)
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.bocha.httpx.Client", return_value=mock_client):
        backend = BochaBackend(api_key="key")
        result = backend.search("test query", max_results=5, timeout_ms=5000)
    items = result.get("items", [])
    assert len(items) == 2
    assert items[0]["title"] == "页面标题"
    assert items[0]["url"] == "https://example.com/page1"
    assert items[0]["snippet"] == "摘要片段"
    assert items[0].get("published_at") == "2024-07-22T00:00:00+08:00"
    assert items[0].get("meta", {}).get("siteName") == "Example"
    assert "siteIcon" in items[0].get("meta", {})
    assert items[1]["title"] == "Second Page"
    assert items[1]["url"] == "https://example.com/page2"
    assert items[1]["snippet"] == "Snippet only"


def test_bocha_backend_authorization_header():
    """请求头含 Authorization: Bearer <api_key>。"""
    raw = _load_fixture("results_basic.json")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = json.loads(raw)
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.bocha.httpx.Client", return_value=mock_client):
        backend = BochaBackend(api_key="secret-key")
        result = backend.search("q", max_results=2, timeout_ms=5000)
    assert "items" in result
    call_kw = mock_client.post.call_args[1]
    assert call_kw.get("headers", {}).get("Authorization") == "Bearer secret-key"


@pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "1" or not (os.getenv("BOCHA_API_KEY") or "").strip(),
    reason="INTEGRATION_TESTS=1 and BOCHA_API_KEY required",
)
def test_bocha_backend_integration_real_request():
    """有 BOCHA_API_KEY 且 INTEGRATION_TESTS=1 时跑一次真实请求；默认 CI 不跑。"""
    backend = BochaBackend(
        api_key=(os.getenv("BOCHA_API_KEY") or "").strip(),
        base_url=os.getenv("BOCHA_BASE_URL") or None,
    )
    result = backend.search("2024 tech news", max_results=3, timeout_ms=15000)
    items = result.get("items", [])
    assert isinstance(items, list)
    for it in items:
        assert "title" in it and "url" in it and "snippet" in it
        assert it.get("provider") == "bocha"
        assert it["url"].startswith("http://") or it["url"].startswith("https://")
