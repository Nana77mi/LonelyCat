"""HttpxFetchBackend tests: mock httpx, no network."""

import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from worker.tools.web_backends.errors import (
    WebBlockedError,
    WebInvalidInputError,
    WebNetworkError,
    WebTimeoutError,
)
from worker.tools.web_backends.http_fetch import HttpxFetchBackend

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures", "web_fetch")


def _load_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_http_fetch_backend_html_extracts_visible_text_and_truncates():
    """Mock httpx 返回 html_with_script_style；断言 script/style 不出现在 text。"""
    html = _load_fixture("html_with_script_style.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.http_fetch.httpx.Client", return_value=mock_client):
        backend = HttpxFetchBackend()
        out = backend.fetch("https://example.com/page", timeout_ms=5000)
    assert out["status_code"] == 200
    assert "url" in out and "text" in out and "truncated" in out
    text = out["text"]
    assert "Visible paragraph one" in text
    assert "Visible paragraph two" in text
    assert "Visible paragraph three" in text
    assert "should not appear" not in text
    assert "nope" not in text
    assert "document.write" not in text


def test_http_fetch_backend_plain_text_returns_text():
    """Mock 返回 plain_text.txt；text 为原样。"""
    raw = _load_fixture("plain_text.txt")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = raw
    mock_resp.headers = {"content-type": "text/plain"}
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.http_fetch.httpx.Client", return_value=mock_client):
        backend = HttpxFetchBackend()
        out = backend.fetch("https://example.com/txt", timeout_ms=5000)
    assert "Plain text content line one" in out["text"]
    assert out["truncated"] is False


def test_http_fetch_backend_invalid_scheme_raises_invalid_input():
    """url=ftp://… 或 file://… 抛 WebInvalidInputError。"""
    backend = HttpxFetchBackend()
    with pytest.raises(WebInvalidInputError):
        backend.fetch("ftp://example.com", timeout_ms=5000)
    with pytest.raises(WebInvalidInputError):
        backend.fetch("file:///tmp/x", timeout_ms=5000)


def test_http_fetch_backend_timeout_raises_timeout():
    """Mock timeout → WebTimeoutError。"""
    with patch("worker.tools.web_backends.http_fetch.httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.TimeoutException("timeout")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_cls.return_value = mock_client
        backend = HttpxFetchBackend()
        with pytest.raises(WebTimeoutError):
            backend.fetch("https://example.com", timeout_ms=5000)


def test_http_fetch_backend_connect_error_raises_network_error():
    """Mock ConnectError → WebNetworkError。"""
    with patch("worker.tools.web_backends.http_fetch.httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_cls.return_value = mock_client
        backend = HttpxFetchBackend()
        with pytest.raises(WebNetworkError):
            backend.fetch("https://example.com", timeout_ms=5000)


def test_http_fetch_backend_403_or_429_raises_web_blocked():
    """Mock status 403/429 → WebBlockedError。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = ""
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    with patch("worker.tools.web_backends.http_fetch.httpx.Client", return_value=mock_client):
        backend = HttpxFetchBackend()
        with pytest.raises(WebBlockedError):
            backend.fetch("https://example.com", timeout_ms=5000)


def test_http_fetch_backend_status_200_body_captcha_raises_web_blocked():
    """Body 含 captcha → WebBlockedError。"""
    html = _load_fixture("blocked_keyword_only.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_resp.headers = {"content-type": "text/html"}
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    with patch("worker.tools.web_backends.http_fetch.httpx.Client", return_value=mock_client):
        backend = HttpxFetchBackend()
        with pytest.raises(WebBlockedError):
            backend.fetch("https://example.com", timeout_ms=5000)


def test_http_fetch_backend_non_text_content_type_returns_empty_text_not_error():
    """content-type=image/png → text==""，truncated==False，不抛错。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ""
    mock_resp.headers = {"content-type": "image/png"}
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    with patch("worker.tools.web_backends.http_fetch.httpx.Client", return_value=mock_client):
        backend = HttpxFetchBackend()
        out = backend.fetch("https://example.com/img.png", timeout_ms=5000)
    assert out["status_code"] == 200
    assert out["text"] == ""
    assert out["truncated"] is False
    assert "image/png" in (out.get("content_type") or "")
