"""webfetch 解析层：HTML → title + extracted_text（readability / trafilatura / fallback）。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from worker.tools.webfetch.models import WebFetchRaw

EXTRACTION_METHOD_READABILITY = "readability"
EXTRACTION_METHOD_TRAFILATURA = "trafilatura"
EXTRACTION_METHOD_FALLBACK = "fallback"
EXTRACTION_METHOD_NONE = "none"


def _is_html_content_type(content_type: str) -> bool:
    if not content_type or not isinstance(content_type, str):
        return False
    ct = content_type.split(";")[0].strip().lower()
    return "html" in ct or ct in ("text/plain", "application/xhtml+xml", "application/xml", "text/xml")


def _decode_body(raw: WebFetchRaw) -> str:
    try:
        return raw.body_bytes.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_readability(html: str) -> Tuple[Optional[str], Optional[str]]:
    """readability-lxml 提取正文与标题；失败返回 (None, None)。"""
    if not html or len(html.strip()) < 10:
        return (None, None)
    try:
        from readability import Document
        doc = Document(html)
        title = doc.title() or ""
        text = doc.summary()
        if not text:
            return (None, None)
        from html.parser import HTMLParser
        class _StripTags(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts: List[str] = []
            def handle_data(self, data: str) -> None:
                self.parts.append(data)
            def get_text(self) -> str:
                return re.sub(r"\s+", " ", "".join(self.parts)).strip()
        parser = _StripTags()
        parser.feed(text)
        body = parser.get_text()
        if not body:
            return (None, None)
        return (body, title.strip() or None)
    except Exception:
        return (None, None)


def _extract_trafilatura(html: str) -> Tuple[Optional[str], Optional[str]]:
    """trafilatura 提取正文与标题；失败返回 (None, None)。"""
    if not html or len(html.strip()) < 10:
        return (None, None)
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=True)
        if not text or not text.strip():
            return (None, None)
        meta = trafilatura.extract_metadata(html)
        title_str = (getattr(meta, "title", None) or "") if meta else ""
        return (text.strip(), title_str.strip() or None)
    except Exception:
        return (None, None)


def _fallback_with_bs4(html: str) -> Tuple[str, str]:
    """BeautifulSoup.get_text() 兜底；保留段落（p 换行）。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    title = ""
    title_tag = soup.find("title")
    if title_tag is not None:
        title = title_tag.get_text(separator=" ", strip=True)
    text = soup.get_text(separator="\n\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return (text or "", title or "")


def _fallback_with_parser(html: str) -> Tuple[str, str]:
    """无 bs4 时用 html.parser 提取可见文本与 <title>。"""
    from html.parser import HTMLParser
    title_parts: List[str] = []
    text_parts: List[str] = []
    in_script_style = False
    in_title = False

    class _Parser(HTMLParser):
        def handle_starttag(self, tag: str, attrs: list) -> None:
            nonlocal in_script_style, in_title
            tag_lower = tag.lower()
            if tag_lower in ("script", "style"):
                in_script_style = True
            elif tag_lower == "title":
                in_title = True

        def handle_endtag(self, tag: str) -> None:
            nonlocal in_script_style, in_title
            tag_lower = tag.lower()
            if tag_lower in ("script", "style"):
                in_script_style = False
            elif tag_lower == "title":
                in_title = False

        def handle_data(self, data: str) -> None:
            if in_title:
                title_parts.append(data)
            elif not in_script_style and data:
                text_parts.append(data)

    try:
        parser = _Parser()
        parser.feed(html)
        title = " ".join(title_parts).strip()
        text = re.sub(r"\s+", " ", " ".join(text_parts)).strip()
        text = re.sub(r" +", " ", text)
        return (text, title)
    except Exception:
        return ("", "")


def _extract_fallback(html: str) -> Tuple[str, str]:
    """兜底：优先 BeautifulSoup，不可用时用 html.parser。"""
    if not html:
        return ("", "")
    try:
        return _fallback_with_bs4(html)
    except Exception:
        return _fallback_with_parser(html)


def extract_html(raw: WebFetchRaw) -> Dict[str, Any]:
    """从 WebFetchRaw 提取 title、extracted_text、extraction_method；text = extracted_text（alias）。"""
    content_type = (raw.headers.get("content-type") or "").strip()
    if not _is_html_content_type(content_type):
        return {
            "title": "",
            "extracted_text": "",
            "extraction_method": EXTRACTION_METHOD_NONE,
            "text": "",
            "error": "unsupported_content_type",
            "paragraphs_count": 0,
        }
    html = _decode_body(raw)
    if not html.strip():
        return {
            "title": "",
            "extracted_text": "",
            "extraction_method": EXTRACTION_METHOD_FALLBACK,
            "text": "",
            "paragraphs_count": 0,
        }
    text, title = _extract_readability(html)
    method = EXTRACTION_METHOD_READABILITY
    if text is None or not (text or "").strip():
        text, title = _extract_trafilatura(html)
        method = EXTRACTION_METHOD_TRAFILATURA
    if text is None or not (text or "").strip():
        text, title = _extract_fallback(html)
        method = EXTRACTION_METHOD_FALLBACK
    text = (text or "").strip()
    title = (title or "").strip()
    if title and title.lower() in ("[no-title]", "[no title]"):
        title = ""
    if not title:
        _, title_fb = _extract_fallback(html)
        title = (title_fb or "").strip()
    paragraphs_count = len(split_paragraphs(text))
    return {
        "title": title,
        "extracted_text": text,
        "text": text,
        "extraction_method": method,
        "paragraphs_count": paragraphs_count,
    }


def split_paragraphs(text: str) -> List[str]:
    """按空行分割为段落列表 p1, p2, ... pn；空字符串返回 []。"""
    if not text or not isinstance(text, str):
        return []
    parts = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in parts if p.strip()]
