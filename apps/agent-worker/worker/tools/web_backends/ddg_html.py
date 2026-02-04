"""DDGHtmlBackend: DuckDuckGo HTML 搜索后端，无 key、无 Docker；解析用标准库。"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Dict, List
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

from worker.tools.web_backends.errors import (
    WebBlockedError,
    WebNetworkError,
    WebParseError,
    WebTimeoutError,
)

DDG_HTML_URL = "https://html.duckduckgo.com/html/"
USER_AGENT = "Mozilla/5.0 (compatible; LonelyCat/1.0; +https://github.com/lonelycat)"
ACCEPT_LANGUAGE = "en-US,en;q=0.9"
NO_RESULTS_PATTERN = re.compile(r"no\s+results", re.I)
# 优先看 status 403/429；body 关键词用小写匹配，避免误伤（captcha / unusual traffic / blocked）
BLOCKED_KEYWORDS = ("captcha", "unusual traffic", "blocked")


def _body_indicates_blocked(text: str) -> bool:
    """Body 含 blocked 关键词（小写匹配）时返回 True。"""
    if not text or not isinstance(text, str):
        return False
    lower = text.lower()
    return any(kw in lower for kw in BLOCKED_KEYWORDS)


def extract_target_url(raw_url: str) -> str:
    """从 DDG 跳转 URL 解析真实目标；若含 uddg 则解码返回；解码结果非 http(s) 则返回 raw_url。"""
    if not raw_url or not isinstance(raw_url, str):
        return raw_url or ""
    raw_url = raw_url.strip()
    parsed = urlparse(raw_url)
    if parsed.netloc == "duckduckgo.com" and parsed.path.rstrip("/").endswith("/l"):
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg")
        if uddg:
            try:
                decoded = unquote(uddg[0])
            except Exception:
                return raw_url
            if decoded.startswith("http://") or decoded.startswith("https://"):
                return decoded
            return raw_url
    return raw_url


class _DDGResultParser(HTMLParser):
    """解析 DDG HTML 结果页：.result 块内 .result__a 的 href/文本 与 .result__snippet 文本。"""

    def __init__(self) -> None:
        super().__init__()
        self._results: List[Dict[str, str]] = []
        self._in_result = False
        self._in_a = False
        self._in_snippet = False
        self._current_href = ""
        self._current_title: List[str] = []
        self._current_snippet: List[str] = []
        self._result_depth = 0

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        attrd = dict(attrs)
        cls = (attrd.get("class") or "").strip()
        if tag == "div" and "result" in cls.split():
            self._result_depth += 1
            if self._result_depth == 1:
                self._in_result = True
                self._current_href = ""
                self._current_title = []
                self._current_snippet = []
        if tag == "a" and self._in_result:
            if "result__a" in cls.split():
                self._in_a = True
                self._current_href = attrd.get("href") or ""
                self._current_title = []
            elif "result__snippet" in cls.split():
                self._in_snippet = True
                self._current_snippet = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._in_result:
            self._result_depth -= 1
            if self._result_depth == 0:
                self._in_result = False
                title = "".join(self._current_title).strip()
                snippet = "".join(self._current_snippet).strip()
                url = extract_target_url(self._current_href)
                if url or title or snippet:
                    self._results.append({
                        "title": title or "",
                        "url": url,
                        "snippet": snippet or "",
                    })
        if tag == "a":
            self._in_a = False
            self._in_snippet = False

    def handle_data(self, data: str) -> None:
        if self._in_a:
            self._current_title.append(data)
        if self._in_snippet:
            self._current_snippet.append(data)

    def get_results(self) -> List[Dict[str, str]]:
        return self._results


def parse_ddg_html(html: str) -> List[Dict[str, str]]:
    """解析 DDG HTML 结果页，返回每项含 title/url/snippet 的列表；url 已经 extract_target_url。"""
    if not html or not isinstance(html, str):
        return []
    parser = _DDGResultParser()
    try:
        parser.feed(html)
    except Exception:
        return []
    return parser.get_results()


class DDGHtmlBackend:
    """DuckDuckGo HTML 后端：GET html.duckduckgo.com/html/?q=，解析结果；无 key。"""

    backend_id: str = "ddg_html"

    def search(self, query: str, max_results: int, timeout_ms: int) -> List[Dict[str, Any]]:
        """请求 DDG HTML 并解析；超时/403/解析失败抛对应错误码。"""
        timeout_sec = max(1, timeout_ms / 1000.0)
        url = DDG_HTML_URL + "?q=" + quote(query.strip())
        headers = {"User-Agent": USER_AGENT, "Accept-Language": ACCEPT_LANGUAGE}
        try:
            with httpx.Client(timeout=timeout_sec) as client:
                resp = client.get(url, headers=headers)
        except httpx.TimeoutException as e:
            raise WebTimeoutError(str(e)[:500]) from e
        except httpx.RequestError as e:
            raise WebNetworkError(str(e)[:500]) from e

        if resp.status_code in (403, 429):
            raise WebBlockedError(f"HTTP {resp.status_code}")
        if _body_indicates_blocked(resp.text):
            raise WebBlockedError("Page indicates block or captcha")

        items = parse_ddg_html(resp.text)
        if not items and not NO_RESULTS_PATTERN.search(resp.text):
            raise WebParseError("No result blocks parsed and page is not 'no results'")
        return items[: max(1, min(max_results, 10))]
