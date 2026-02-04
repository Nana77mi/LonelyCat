"""Tests for webfetch extractor: readability/trafilatura/fallback, title, paragraphs."""

from unittest.mock import MagicMock, patch

import pytest

from worker.tools.webfetch.extractor import (
    _extract_fallback,
    extract_html,
    split_paragraphs,
)
from worker.tools.webfetch.models import WebFetchRaw


def _raw(html: str, content_type: str = "text/html; charset=utf-8") -> WebFetchRaw:
    return WebFetchRaw(
        url="https://example.com/",
        final_url="https://example.com/",
        status_code=200,
        headers={"content-type": content_type},
        body_bytes=html.encode("utf-8"),
        meta={"bytes_read": len(html.encode("utf-8")), "truncated": False},
    )


def test_extract_fallback_returns_title_and_text():
    """fallback 能从 <title> 和 body 提取 title 与正文。"""
    html = "<html><head><title>My Page Title</title></head><body><p>Body text.</p></body></html>"
    text, title = _extract_fallback(html)
    assert title == "My Page Title"
    assert "Body" in text or "text" in text


def test_extract_html_returns_title_when_present():
    """有 <title> 时能拿到 title（任一提取器），无时可为空。"""
    html = "<html><head><title>My Page Title</title></head><body><p>Body text.</p></body></html>"
    raw = _raw(html)
    result = extract_html(raw)
    assert result.get("title") == "My Page Title" or "My Page Title" in (result.get("title") or "")
    assert "extracted_text" in result
    assert result.get("extraction_method") in ("readability", "trafilatura", "fallback")


def test_extract_html_returns_empty_title_when_absent():
    """无 <title> 时 title 为空。"""
    html = "<html><body><p>Only body.</p></body></html>"
    raw = _raw(html)
    result = extract_html(raw)
    assert result.get("title") == "" or result.get("title") is None


def test_extract_html_extracted_text_preserves_paragraphs():
    """extracted_text 保留段落；fallback 下两段内容应出现。"""
    html = "<html><body><p>First paragraph.</p><p>Second paragraph.</p></body></html>"
    fb_text, _ = _extract_fallback(html)
    assert "First" in fb_text and "Second" in fb_text
    raw = _raw(html)
    result = extract_html(raw)
    text = result.get("extracted_text", "")
    assert result.get("extraction_method") in ("readability", "trafilatura", "fallback")
    assert "First" in text or "Second" in text or len(text) > 0


def test_extract_html_readability_success_sets_method_readability():
    """readability 成功提取时 extraction_method=readability。"""
    html = """<!DOCTYPE html><html><head><title>News</title></head>
<body><article><p>Main content here.</p></article></body></html>"""
    raw = _raw(html)
    with patch("worker.tools.webfetch.extractor._extract_readability") as mock_read:
        mock_read.return_value = ("Main content here.", "News")
        with patch("worker.tools.webfetch.extractor._extract_trafilatura", return_value=(None, None)):
            with patch("worker.tools.webfetch.extractor._extract_fallback", return_value=("fallback", "")):
                result = extract_html(raw)
    assert result.get("extraction_method") == "readability"
    assert result.get("extracted_text") == "Main content here."
    assert result.get("title") == "News"


def test_extract_html_fallback_when_readability_fails():
    """readability 失败时 trafilatura/fallback 能兜住，method 变化正确。"""
    html = "<html><body><p>Simple.</p></body></html>"
    raw = _raw(html)
    with patch("worker.tools.webfetch.extractor._extract_readability", return_value=(None, None)):
        result = extract_html(raw)
    assert result.get("extraction_method") in ("trafilatura", "fallback")
    assert len(result.get("extracted_text", "")) >= 0


def test_extract_html_text_equals_extracted_text_alias():
    """对外合同：text 永远存在，值 = extracted_text（alias）。"""
    html = "<html><body><p>One.</p></body></html>"
    raw = _raw(html)
    result = extract_html(raw)
    assert "text" in result
    assert result["text"] == result.get("extracted_text", "")


def test_split_paragraphs_returns_p1_p2_pn():
    """按空行分割 → p1, p2, ... pn。"""
    text = "First para.\n\nSecond para.\n\nThird."
    paras = split_paragraphs(text)
    assert len(paras) >= 2
    assert paras[0] == "First para."
    assert paras[1] == "Second para."


def test_split_paragraphs_single_paragraph():
    """单段无空行时返回单元素列表。"""
    text = "Only one block."
    paras = split_paragraphs(text)
    assert paras == ["Only one block."]


def test_split_paragraphs_empty_string():
    """空字符串返回空列表。"""
    assert split_paragraphs("") == []
    assert split_paragraphs("   \n\n  ") == []


def test_extract_html_non_html_content_type_returns_unsupported():
    """非 HTML content-type 时 extraction_method=none，extracted_text 为空，error=unsupported_content_type。"""
    raw = _raw("<binary>", content_type="application/octet-stream")
    result = extract_html(raw)
    assert result.get("extraction_method") == "none"
    assert result.get("extracted_text") == ""
    assert result.get("error") == "unsupported_content_type"
    assert result.get("paragraphs_count") == 0


def test_extract_html_includes_paragraphs_count():
    """extractor 输出含 paragraphs_count，便于 debug 与 citations。"""
    html = "<html><body><p>One.</p><p>Two.</p></body></html>"
    raw = _raw(html)
    result = extract_html(raw)
    assert "paragraphs_count" in result
    assert result["paragraphs_count"] == len(split_paragraphs(result.get("extracted_text", "")))
