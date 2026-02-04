"""HttpxFetchBackend: 真实 httpx GET 抓取，仅 http(s)，无 key。"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Dict

import httpx

from worker.tools.web_backends.errors import (
    WebBlockedError,
    WebInvalidInputError,
    WebNetworkError,
    WebTimeoutError,
)

USER_AGENT = "Mozilla/5.0 (compatible; LonelyCat/1.0; +https://github.com/lonelycat)"
ACCEPT_LANGUAGE = "en-US,en;q=0.9"
BLOCKED_KEYWORDS = ("captcha", "unusual traffic", "blocked")
TEXT_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml+xml", "application/xml", "text/xml")
DEFAULT_TEXT_MAX = 100_000


def _is_http_or_https(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    return u.startswith("http://") or u.startswith("https://")


def _body_indicates_blocked(text: str) -> bool:
    if not text or not isinstance(text, str):
        return False
    return any(kw in text.lower() for kw in BLOCKED_KEYWORDS)


def _is_text_content_type(ct: str) -> bool:
    if not ct or not isinstance(ct, str):
        return False
    ct_lower = ct.split(";")[0].strip().lower()
    return any(ct_lower.startswith(t) for t in TEXT_CONTENT_TYPES)


class _VisibleTextParser(HTMLParser):
    """提取 HTML 可见文本，跳过 script/style。"""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip and data:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        return re.sub(r"\s+", " ", raw).strip()


def _extract_visible_text(html: str) -> str:
    if not html or not isinstance(html, str):
        return ""
    parser = _VisibleTextParser()
    try:
        parser.feed(html)
        return parser.get_text()
    except Exception:
        return html[:DEFAULT_TEXT_MAX]


def _get_text_max() -> int:
    import os
    try:
        return max(1000, int(os.getenv("WEB_FETCH_TEXT_MAX", str(DEFAULT_TEXT_MAX))))
    except (TypeError, ValueError):
        return DEFAULT_TEXT_MAX


class HttpxFetchBackend:
    """真实 httpx GET 抓取；仅 http(s)，超时/403/429/body blocked 抛对应错误码。"""

    backend_id: str = "httpx"

    def fetch(self, url: str, timeout_ms: int) -> Dict[str, Any]:
        if not _is_http_or_https(url):
            raise WebInvalidInputError("url must be http:// or https://")
        url = url.strip()
        timeout_sec = max(1, timeout_ms / 1000.0)
        text_max = _get_text_max()
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

        content_type = (resp.headers.get("content-type") or "").strip()
        if not _is_text_content_type(content_type):
            return {
                "url": url,
                "status_code": resp.status_code,
                "content_type": content_type,
                "text": "",
                "truncated": False,
            }

        raw_text = resp.text
        if "html" in content_type.lower():
            text = _extract_visible_text(raw_text)
        else:
            text = raw_text if isinstance(raw_text, str) else ""
        truncated = len(text) > text_max
        if truncated:
            text = text[:text_max]
        return {
            "url": url,
            "status_code": resp.status_code,
            "content_type": content_type,
            "text": text,
            "truncated": truncated,
        }
