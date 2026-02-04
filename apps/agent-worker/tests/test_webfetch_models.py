"""Tests for webfetch models: WebFetchRaw, error codes."""

import pytest

from worker.tools.webfetch.models import (
    WEB_FETCH_ERROR_CODES,
    WebFetchRaw,
)


def test_web_fetch_raw_has_required_fields():
    """WebFetchRaw 含 url, final_url, status_code, headers, body_bytes, error, meta。"""
    raw = WebFetchRaw(
        url="https://example.com",
        final_url="https://example.com/",
        status_code=200,
        headers={"content-type": "text/html"},
        body_bytes=b"<html>ok</html>",
        error=None,
        meta={"bytes_read": 18},
    )
    assert raw.url == "https://example.com"
    assert raw.final_url == "https://example.com/"
    assert raw.status_code == 200
    assert raw.headers.get("content-type") == "text/html"
    assert raw.body_bytes == b"<html>ok</html>"
    assert raw.error is None
    assert raw.meta.get("bytes_read") == 18


def test_web_fetch_raw_to_canonical_dict_includes_text_and_truncated():
    """to_canonical_dict 含 url, status_code, content_type, text, truncated, error, meta。"""
    raw = WebFetchRaw(
        url="https://a.com",
        final_url="https://a.com",
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        body_bytes=b"<p>hello</p>",
        meta={"bytes_read": 14, "truncated": False},
    )
    d = raw.to_canonical_dict()
    assert d["url"] == "https://a.com"
    assert d["final_url"] == "https://a.com"
    assert d["status_code"] == 200
    assert "text/html" in d["content_type"]
    assert d["text"] == "<p>hello</p>"
    assert d["truncated"] is False
    assert "meta" in d
    assert d["meta"].get("bytes_read") == 14


def test_web_fetch_raw_with_error_and_truncated():
    """error 非空、truncated=True 时 to_canonical_dict 正确。"""
    raw = WebFetchRaw(
        url="https://b.com",
        final_url="https://b.com",
        status_code=200,
        headers={},
        body_bytes=b"x" * 100,
        error=None,
        meta={"bytes_read": 100, "truncated": True},
    )
    d = raw.to_canonical_dict()
    assert d["truncated"] is True
    assert d["meta"]["bytes_read"] == 100


def test_web_fetch_error_codes_include_ssrf_and_network_unreachable():
    """WEB_FETCH_ERROR_CODES 含 ssrf_blocked、network_unreachable。"""
    assert "ssrf_blocked" in WEB_FETCH_ERROR_CODES
    assert "network_unreachable" in WEB_FETCH_ERROR_CODES
    assert "timeout_connect" in WEB_FETCH_ERROR_CODES
    assert "http_403" in WEB_FETCH_ERROR_CODES
