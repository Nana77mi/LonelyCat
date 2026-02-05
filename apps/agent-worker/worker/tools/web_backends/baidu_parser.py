"""百度 SERP HTML 解析（纯函数，无网络依赖）。供 baidu_html backend 使用。"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

# 验证码/安全验证关键词，用于识别拦截页
CAPTCHA_KEYWORDS = ("验证码", "安全验证")


def _body_indicates_captcha(text: str) -> bool:
    """Body 含验证码/安全验证关键词时返回 True。"""
    if not text or not isinstance(text, str):
        return False
    return any(kw in text for kw in CAPTCHA_KEYWORDS)


class _BaiduResultParser(HTMLParser):
    """解析百度 HTML 结果页：.result / .c-container 块内 h3.t a 的 href/文本 与 .c-abstract 文本。"""

    def __init__(self) -> None:
        super().__init__()
        self._results: List[Dict[str, str]] = []
        self._in_result = False
        self._in_title_a = False
        self._in_abstract = False
        self._current_href = ""
        self._current_title: List[str] = []
        self._current_snippet: List[str] = []
        self._result_depth = 0

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        attrd = dict(attrs)
        cls = (attrd.get("class") or "").strip().split()
        if tag == "div" and ("result" in cls or "c-container" in cls):
            self._result_depth += 1
            if self._result_depth == 1:
                self._in_result = True
                self._current_href = ""
                self._current_title = []
                self._current_snippet = []
        if tag == "a" and self._in_result and not self._in_title_a:
            self._in_title_a = True
            self._current_href = attrd.get("href") or ""
            self._current_title = []
        if tag == "div" and self._in_result and "c-abstract" in cls:
            self._in_abstract = True
            self._current_snippet = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._in_result:
            self._result_depth -= 1
            if self._result_depth == 0:
                self._in_result = False
                title = "".join(self._current_title).strip()
                snippet = "".join(self._current_snippet).strip()
                url = (self._current_href or "").strip()
                if url and (url.startswith("http://") or url.startswith("https://")) and title:
                    self._results.append({
                        "title": title,
                        "url": url,
                        "snippet": snippet or "",
                    })
        if tag == "a":
            self._in_title_a = False
        if tag == "div":
            self._in_abstract = False

    def handle_data(self, data: str) -> None:
        if self._in_title_a:
            self._current_title.append(data)
        if self._in_abstract:
            self._current_snippet.append(data)

    def get_results(self) -> List[Dict[str, str]]:
        return self._results


def parse_baidu_html(html: str) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """解析百度 HTML 结果页，返回 (items, error_code_or_none)。
    items 每项含 title/url/snippet；snippet 可空。
    拦截页（验证码/安全验证）返回 ([], "captcha_required")；
    解析失败或空输入返回 ([], "parse_failed")；
    无结果页可返回 ([], None)。
    """
    if not html or not isinstance(html, str):
        return [], "parse_failed"
    html_stripped = html.strip()
    if not html_stripped:
        return [], "parse_failed"
    if _body_indicates_captcha(html):
        return [], "captcha_required"
    parser = _BaiduResultParser()
    try:
        parser.feed(html)
    except Exception:
        return [], "parse_failed"
    results = parser.get_results()
    if not results:
        return [], "parse_failed"
    return results, None
