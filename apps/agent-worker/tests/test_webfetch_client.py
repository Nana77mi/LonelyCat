"""Tests for webfetch client: max_bytes, retry, SSRF, proxy, URL normalize."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from worker.tools.web_backends.errors import (
    WebInvalidInputError,
    WebSSRFBlockedError,
)
from worker.tools.webfetch.client import WebfetchClient
from worker.tools.webfetch.models import WebFetchRaw


def test_client_ssrf_blocks_127_0_0_1():
    """127.0.0.1 必须直接拒绝，error=ssrf_blocked。"""
    client = WebfetchClient(timeout_connect_sec=5, timeout_read_sec=20, max_bytes=2 * 1024 * 1024)
    with pytest.raises(WebSSRFBlockedError):
        client.fetch("https://127.0.0.1/path")


def test_client_ssrf_blocks_localhost():
    """localhost 解析为环回时拒绝。"""
    client = WebfetchClient(timeout_connect_sec=5, timeout_read_sec=20, max_bytes=5 * 1024 * 1024)
    with patch("worker.tools.webfetch.ssrf.socket.gethostbyname_ex", return_value=(["localhost"], [], ["127.0.0.1"])):
        with pytest.raises(WebSSRFBlockedError):
            client.fetch("https://localhost/page")


def test_client_invalid_scheme_raises_invalid_input():
    """ftp:// 或 file:// 抛 WebInvalidInputError。"""
    client = WebfetchClient(timeout_connect_sec=5, timeout_read_sec=20, max_bytes=5 * 1024 * 1024)
    with pytest.raises(WebInvalidInputError):
        client.fetch("ftp://example.com")
    with pytest.raises(WebInvalidInputError):
        client.fetch("file:///tmp/x")


def test_client_max_bytes_returns_truncated_and_meta_bytes_read():
    """响应体超过 max_bytes 时返回 truncated=True 且 meta.bytes_read 为实际读取字节。"""
    body_truncated = b"x" * 3000
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html"}
    mock_resp.url = "https://example.com/"
    mock_resp.iter_bytes = lambda chunk_size: [body_truncated]

    client = WebfetchClient(timeout_connect_sec=5, timeout_read_sec=20, max_bytes=3000)
    with patch("worker.tools.webfetch.client.check_ssrf_blocked"):
        with patch.object(client, "_do_request", return_value=(mock_resp, body_truncated)):
            raw = client.fetch("https://example.com/")
    assert isinstance(raw, WebFetchRaw)
    assert raw.meta.get("truncated") is True
    assert raw.meta.get("bytes_read") == 3000


def test_client_retry_only_for_429_not_4xx():
    """重试仅对 429/5xx/timeout，对 4xx 不重试。"""
    mock_resp_403 = MagicMock()
    mock_resp_403.status_code = 403
    mock_resp_403.headers = {}
    mock_resp_403.url = "https://example.com/"
    mock_resp_403.iter_bytes = lambda chunk_size: [b""]

    client = WebfetchClient(timeout_connect_sec=5, timeout_read_sec=20, max_bytes=5 * 1024 * 1024)
    call_count = 0

    def fake_request(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return (mock_resp_403, b"")

    with patch("worker.tools.webfetch.client.check_ssrf_blocked"):
        with patch.object(client, "_do_request", side_effect=fake_request):
            raw = client.fetch("https://example.com/")
    assert raw.status_code == 403
    assert raw.error == "http_403"
    assert call_count == 1


def test_client_retry_429_then_200():
    """429 后重试得到 200 则成功。"""
    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_429.headers = {}
    mock_429.url = "https://example.com/"
    mock_429.iter_bytes = lambda chunk_size: [b""]
    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.headers = {"content-type": "text/html"}
    mock_200.url = "https://example.com/"
    mock_200.iter_bytes = lambda chunk_size: [b"<html>ok</html>"]

    client = WebfetchClient(timeout_connect_sec=5, timeout_read_sec=20, max_bytes=5 * 1024 * 1024)
    call_count = 0

    def fake_request(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return (mock_429, b"")
        return (mock_200, b"<html>ok</html>")

    with patch("worker.tools.webfetch.client.check_ssrf_blocked"):
        with patch.object(client, "_do_request", side_effect=fake_request):
            raw = client.fetch("https://example.com/")
    assert raw.status_code == 200
    assert call_count == 2


def test_client_normalizes_url_before_fetch():
    """请求前对 URL 做规范化（去 fragment、去跟踪参数）。"""
    client = WebfetchClient(timeout_connect_sec=5, timeout_read_sec=20, max_bytes=5 * 1024 * 1024)
    requested_url = None

    def capture_request(url, *args, **kwargs):
        nonlocal requested_url
        requested_url = url
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.url = url
        mock_resp.iter_bytes = lambda chunk_size: [b"<html/>"]
        return (mock_resp, b"<html/>")

    with patch("worker.tools.webfetch.client.check_ssrf_blocked"):
        with patch.object(client, "_do_request", side_effect=capture_request):
            client.fetch("https://example.com/p?utm_source=foo#section")
    assert requested_url is not None
    assert "utm_source" not in requested_url
    assert "#" not in requested_url
