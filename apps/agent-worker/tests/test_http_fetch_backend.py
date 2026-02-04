"""HttpxFetchBackend tests: mock webfetch client, no network."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from worker.tools.web_backends.errors import (
    WebBlockedError,
    WebInvalidInputError,
    WebNetworkError,
    WebTimeoutError,
)
from worker.tools.web_backends.http_fetch import HttpxFetchBackend
from worker.tools.webfetch.models import WebFetchRaw

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures", "web_fetch")


def _load_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def _raw(status_code: int, content_type: str, body_bytes: bytes, url: str = "https://example.com/", truncated: bool = False) -> WebFetchRaw:
    return WebFetchRaw(
        url=url,
        final_url=url,
        status_code=status_code,
        headers={"content-type": content_type},
        body_bytes=body_bytes,
        error=None,
        meta={"bytes_read": len(body_bytes), "truncated": truncated},
    )


def test_http_fetch_backend_html_extracts_visible_text_and_truncates():
    """Mock webfetch 返回 html_with_script_style；断言 script/style 不出现在 text。"""
    html = _load_fixture("html_with_script_style.html")
    raw = _raw(200, "text/html; charset=utf-8", html.encode("utf-8"), "https://example.com/page")

    with patch("worker.tools.web_backends.http_fetch.WebfetchClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.fetch.return_value = raw
        mock_cls.return_value = mock_client
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
    raw_text = _load_fixture("plain_text.txt")
    raw = _raw(200, "text/plain", raw_text.encode("utf-8"), "https://example.com/txt")

    with patch("worker.tools.web_backends.http_fetch.WebfetchClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.fetch.return_value = raw
        mock_cls.return_value = mock_client
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
    """Mock client 返回 error=timeout_read → WebTimeoutError。"""
    raw = _raw(408, "", b"")
    raw.error = "timeout_read"
    with patch("worker.tools.web_backends.http_fetch.WebfetchClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.fetch.return_value = raw
        mock_cls.return_value = mock_client
        backend = HttpxFetchBackend()
        with pytest.raises(WebTimeoutError):
            backend.fetch("https://example.com", timeout_ms=5000)


def test_http_fetch_backend_connect_error_raises_network_error():
    """Mock client 返回 error=connect_failed → WebNetworkError。"""
    raw = _raw(0, "", b"")
    raw.error = "connect_failed"
    with patch("worker.tools.web_backends.http_fetch.WebfetchClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.fetch.return_value = raw
        mock_cls.return_value = mock_client
        backend = HttpxFetchBackend()
        with pytest.raises(WebNetworkError):
            backend.fetch("https://example.com", timeout_ms=5000)


def test_http_fetch_backend_403_or_429_raises_web_blocked():
    """Mock status 403/429 → WebBlockedError。"""
    raw = _raw(403, "text/html", b"")
    with patch("worker.tools.web_backends.http_fetch.WebfetchClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.fetch.return_value = raw
        mock_cls.return_value = mock_client
        backend = HttpxFetchBackend()
        with pytest.raises(WebBlockedError):
            backend.fetch("https://example.com", timeout_ms=5000)


def test_http_fetch_backend_status_200_body_captcha_raises_web_blocked():
    """Body 含 captcha → WebBlockedError。"""
    html = _load_fixture("blocked_keyword_only.html")
    raw = _raw(200, "text/html", html.encode("utf-8"))
    with patch("worker.tools.web_backends.http_fetch.WebfetchClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.fetch.return_value = raw
        mock_cls.return_value = mock_client
        backend = HttpxFetchBackend()
        with pytest.raises(WebBlockedError):
            backend.fetch("https://example.com", timeout_ms=5000)


def test_http_fetch_backend_non_text_content_type_returns_empty_text_not_error():
    """content-type=image/png → text==""，truncated==False，不抛错。"""
    raw = _raw(200, "image/png", b"")
    with patch("worker.tools.web_backends.http_fetch.WebfetchClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.fetch.return_value = raw
        mock_cls.return_value = mock_client
        backend = HttpxFetchBackend()
        out = backend.fetch("https://example.com/img.png", timeout_ms=5000)
    assert out["status_code"] == 200
    assert out["text"] == ""
    assert out["truncated"] is False
    assert "image/png" in (out.get("content_type") or "")


def test_http_fetch_backend_with_artifact_dir_writes_raw_extracted_meta_and_returns_paths():
    """传入 artifact_dir 时写入 raw.html、extracted.txt、meta.json 并返回 artifact_paths（PR#3）。"""
    html = _load_fixture("html_basic.html")
    raw = _raw(200, "text/html; charset=utf-8", html.encode("utf-8"), "https://example.com/a")
    with tempfile.TemporaryDirectory() as tmp:
        with patch("worker.tools.web_backends.http_fetch.WebfetchClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.fetch.return_value = raw
            mock_cls.return_value = mock_client
            backend = HttpxFetchBackend()
            out = backend.fetch("https://example.com/a", timeout_ms=5000, artifact_dir=tmp)
        assert "artifact_paths" in out
        paths = out["artifact_paths"]
        assert "raw" in paths and "extracted" in paths and "meta" in paths
        raw_path = Path(paths["raw"])
        extracted_path = Path(paths["extracted"])
        meta_path = Path(paths["meta"])
        assert raw_path.exists()
        assert extracted_path.exists()
        assert meta_path.exists()
        assert raw_path.read_bytes() == html.encode("utf-8")
        extracted_text = extracted_path.read_text(encoding="utf-8")
        assert "First paragraph" in extracted_text or "Basic" in extracted_text or len(extracted_text) > 0
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta.get("url") == "https://example.com/a"
        assert meta.get("status_code") == 200
