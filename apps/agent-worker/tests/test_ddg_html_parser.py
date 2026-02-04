"""Parser tests for DDG HTML: parse_ddg_html, extract_target_url (fixture-driven, no network)."""

import os

from worker.tools.web_backends.ddg_html import extract_target_url, parse_ddg_html

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures", "ddg_html")


def _load_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_parse_ddg_html_basic_extracts_title_url_snippet():
    """parse_ddg_html(results_basic.html) 得到至少 2 条，每条含 title/url/snippet，url 非空。"""
    html = _load_fixture("results_basic.html")
    items = parse_ddg_html(html)
    assert len(items) >= 2
    for it in items:
        assert "title" in it
        assert "url" in it
        assert "snippet" in it
        assert it["url"]
    assert items[0]["title"] == "First Result Title"
    assert "example.com" in items[0]["url"]
    assert "Snippet text for first result" in items[0]["snippet"]


def test_extract_target_url_decodes_uddg_redirect():
    """extract_target_url 输入 DDG 跳转 URL（含 uddg=）→ 返回真实 https://... 目标。"""
    raw = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Freal-target.com%2Fpage&rut=abc"
    out = extract_target_url(raw)
    assert out == "https://real-target.com/page"
    # direct URL unchanged
    direct = "https://example.com/page"
    assert extract_target_url(direct) == direct


def test_parse_ddg_html_no_results_returns_empty_list():
    """no_results.html → parse_ddg_html 返回 []。"""
    html = _load_fixture("no_results.html")
    items = parse_ddg_html(html)
    assert items == []


def test_extract_target_url_invalid_uddg_returns_raw():
    """解码结果非 http(s)（如 javascript:）或解码失败 → 返回 raw_url。"""
    raw = "https://duckduckgo.com/l/?uddg=javascript%3Aalert(1)&rut=abc"
    out = extract_target_url(raw)
    assert out == raw
    raw2 = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fok.com%2F"
    assert extract_target_url(raw2) == "https://ok.com/"


def test_parse_ddg_html_no_snippet_returns_items_with_empty_snippet():
    """仅有 title/url、无 result__snippet 时仍返回 items，snippet 置空。"""
    html = _load_fixture("results_no_snippet.html")
    items = parse_ddg_html(html)
    assert len(items) >= 1
    for it in items:
        assert "title" in it and "url" in it and "snippet" in it
        assert it["snippet"] == ""
    assert items[0]["title"] == "Title Only One"
    assert "example.com" in items[0]["url"]
