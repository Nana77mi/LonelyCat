"""Tests for webfetch URL normalization."""

import pytest

from worker.tools.webfetch.url_utils import normalize_fetch_url


def test_normalize_strips_fragment():
    """去掉 #fragment。"""
    assert normalize_fetch_url("https://example.com/page#section") == "https://example.com/page"
    # path 可能为空或 /，query 保留
    out = normalize_fetch_url("https://a.com?q=1#x")
    assert out.startswith("https://a.com") and "q=1" in out and "#" not in out


def test_normalize_removes_tracking_params():
    """移除 utm_*, spm, fbclid 等跟踪参数。"""
    url = "https://example.com/p?utm_source=foo&utm_medium=bar&id=1"
    out = normalize_fetch_url(url)
    assert "utm_source" not in out and "utm_medium" not in out
    assert "id=1" in out

    url2 = "https://a.com?spm=123&q=hello"
    out2 = normalize_fetch_url(url2)
    assert "spm=" not in out2
    assert "q=hello" in out2

    url3 = "https://b.com?fbclid=abc&x=1"
    out3 = normalize_fetch_url(url3)
    assert "fbclid=" not in out3
    assert "x=1" in out3


def test_normalize_preserves_path_and_scheme():
    """保留 path、scheme、host。"""
    u = "https://example.com/path/to?q=1"
    assert normalize_fetch_url(u).startswith("https://example.com/path/to")
    assert "q=1" in normalize_fetch_url(u)


def test_normalize_idempotent():
    """多次规范化结果一致。"""
    u = "https://example.com?a=1&utm_campaign=x#frag"
    assert normalize_fetch_url(normalize_fetch_url(u)) == normalize_fetch_url(u)
