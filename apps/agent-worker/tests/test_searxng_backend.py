"""SearxngBackend tests: mock httpx, no network."""

import json
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from worker.tools.web_backends.errors import (
    WebAuthError,
    WebBadGatewayError,
    WebNetworkError,
    WebParseError,
    WebTimeoutError,
)
from worker.tools.web_backends.searxng import SearxngBackend

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures", "searxng")


def _load_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_searxng_backend_returns_items_and_respects_max_results():
    """Mock httpx 返回 results_basic.json；max_results=2 → 返回 2 条。"""
    raw = _load_fixture("results_basic.json")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = json.loads(raw)
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.searxng.httpx.Client", return_value=mock_client):
        backend = SearxngBackend(base_url="http://localhost:8080")
        items = backend.search("test", max_results=2, timeout_ms=5000)
    assert len(items) == 2
    for it in items:
        assert "title" in it and "url" in it and "snippet" in it
    assert items[0]["title"] == "First Result Title"
    assert "example.com" in items[0]["url"]
    assert items[0].get("provider") == "google"


def test_searxng_backend_timeout_raises_web_timeout():
    """Mock timeout → WebTimeoutError code Timeout。"""
    with patch("worker.tools.web_backends.searxng.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.TimeoutException("timeout")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client
        backend = SearxngBackend(base_url="http://localhost:8080")
        with pytest.raises(WebTimeoutError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "Timeout"


def test_searxng_backend_connect_error_raises_web_network_error():
    """Mock httpx.ConnectError → WebNetworkError code NetworkError。"""
    with patch("worker.tools.web_backends.searxng.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client
        backend = SearxngBackend(base_url="http://localhost:8080")
        with pytest.raises(WebNetworkError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "NetworkError"


def test_searxng_backend_malformed_json_raises_web_parse_error():
    """返回 results_malformed.json 或缺字段 → WebParseError。"""
    raw = _load_fixture("results_malformed.json")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = json.loads(raw)
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.searxng.httpx.Client", return_value=mock_client):
        backend = SearxngBackend(base_url="http://localhost:8080")
        with pytest.raises(WebParseError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebParseError"


def test_searxng_backend_5xx_raises_bad_gateway():
    """Mock 5xx → WebBadGatewayError code BadGateway。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 502
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.searxng.httpx.Client", return_value=mock_client):
        backend = SearxngBackend(base_url="http://localhost:8080")
        with pytest.raises(WebBadGatewayError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "BadGateway"


def test_searxng_backend_json_decode_error_raises_web_parse_error():
    """Mock resp.json() 抛 ValueError（如非 JSON body）→ WebParseError。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = ValueError("Expecting value: line 1 column 1")
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.searxng.httpx.Client", return_value=mock_client):
        backend = SearxngBackend(base_url="http://localhost:8080")
        with pytest.raises(WebParseError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebParseError"


def test_searxng_backend_401_raises_auth_error():
    """Mock 401 → WebAuthError code AuthError。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.searxng.httpx.Client", return_value=mock_client):
        backend = SearxngBackend(base_url="http://localhost:8080")
        with pytest.raises(WebAuthError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "AuthError"


def test_searxng_backend_empty_results_returns_empty_list():
    """Mock results_empty.json → 返回空列表。"""
    raw = _load_fixture("results_empty.json")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = json.loads(raw)
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.searxng.httpx.Client", return_value=mock_client):
        backend = SearxngBackend(base_url="http://localhost:8080")
        items = backend.search("nonexistent", max_results=5, timeout_ms=5000)
    assert items == []
