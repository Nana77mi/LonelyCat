"""Parser tests for Baidu HTML: parse_baidu_html (fixture-driven, no network). TDD: rank 仅由 normalize 层写，parser 不返回 rank。"""

import importlib.util
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures", "baidu_html")

try:
    from worker.tools.web_backends.baidu_parser import parse_baidu_html
except Exception:
    # 无完整 env（protocol/httpx）时仅加载 baidu_parser 模块（无网络依赖）
    _parser_path = os.path.join(TESTS_DIR, "..", "worker", "tools", "web_backends", "baidu_parser.py")
    _spec = importlib.util.spec_from_file_location("baidu_parser", _parser_path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    parse_baidu_html = _mod.parse_baidu_html


def _load_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_parse_baidu_html_basic_extracts_title_url_snippet():
    """parse_baidu_html(results_basic.html) 得到至少 2 条，每条含 title/url/snippet，title/url 非空。"""
    html = _load_fixture("results_basic.html")
    items, err = parse_baidu_html(html)
    assert err is None
    assert len(items) >= 2
    for it in items:
        assert "title" in it and "url" in it and "snippet" in it
        assert it["title"]
        assert it["url"]
    assert items[0]["title"] == "First Result Title"
    assert "example.com" in items[0]["url"]
    assert "Snippet text for first result" in items[0]["snippet"]


def test_parse_baidu_html_captcha_returns_captcha_required():
    """blocked_captcha.html（验证码/安全验证关键词）→ ([], "captcha_required")。"""
    html = _load_fixture("blocked_captcha.html")
    items, err = parse_baidu_html(html)
    assert items == []
    assert err == "captcha_required"


def test_parse_baidu_html_no_results_returns_empty_list():
    """no_results.html（没有找到相关结果）→ 空列表，err 为 None 或 parse_failed。"""
    html = _load_fixture("no_results.html")
    items, err = parse_baidu_html(html)
    assert items == []
    assert err in (None, "parse_failed")


def test_parse_baidu_html_malformed_returns_parse_failed():
    """empty_and_malformed.html（非结果页结构）→ ([], "parse_failed")，不抛异常。"""
    html = _load_fixture("empty_and_malformed.html")
    items, err = parse_baidu_html(html)
    assert items == []
    assert err == "parse_failed"


def test_parse_baidu_html_order_preserved():
    """结果顺序与页面顺序一致，便于上层 normalize 赋 rank。"""
    html = _load_fixture("results_basic.html")
    items, _ = parse_baidu_html(html)
    assert len(items) >= 3
    assert items[0]["title"] == "First Result Title"
    assert items[1]["title"] == "Second Result Title"
    assert "Third" in items[2]["title"] or "Link" in items[2]["title"]


def test_parse_baidu_html_snippet_missing_tolerated():
    """第四条仅有 title/url、无 snippet 时仍返回该项，snippet 置空。"""
    html = _load_fixture("results_basic.html")
    items, _ = parse_baidu_html(html)
    with_snippet = [it for it in items if it.get("snippet")]
    without_snippet = [it for it in items if not it.get("snippet")]
    assert len(items) >= 4
    assert any(it["title"] == "Fourth Title Only" for it in items)
    for it in items:
        assert "snippet" in it
        assert isinstance(it.get("snippet", ""), str)


def test_parse_baidu_html_empty_input_returns_parse_failed():
    """空字符串或非字符串 → ([], "parse_failed")，不抛异常。"""
    items1, err1 = parse_baidu_html("")
    assert items1 == []
    assert err1 == "parse_failed"
    items2, err2 = parse_baidu_html("   ")
    assert items2 == []
    assert err2 == "parse_failed"


def test_parse_baidu_html_link_url_preserved():
    """百度 /link?url= 链接原样返回，不在 parser 层解析落地页。"""
    html = _load_fixture("results_basic.html")
    items, _ = parse_baidu_html(html)
    link_item = next((it for it in items if "baidu.com/link" in it.get("url", "")), None)
    assert link_item is not None
    assert "baidu.com/link" in link_item["url"]
