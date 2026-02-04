"""HttpxFetchBackend: 委托 webfetch client，SSRF/重试/max_bytes/代理；仅 http(s)。"""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from typing import Any, Dict

from worker.tools.web_backends.errors import (
    WebBlockedError,
    WebInvalidInputError,
    WebNetworkError,
    WebTimeoutError,
)
from worker.tools.webfetch.client import WebfetchClient
from worker.tools.webfetch.extractor import extract_html
from worker.tools.webfetch.models import WebFetchRaw

USER_AGENT = "Mozilla/5.0 (compatible; LonelyCat/1.0; +https://github.com/lonelycat)"
ACCEPT_LANGUAGE = "en-US,en;q=0.9"
BLOCKED_KEYWORDS = ("captcha", "unusual traffic", "blocked")
TEXT_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml+xml", "application/xml", "text/xml")
DEFAULT_TEXT_MAX = 100_000
DEFAULT_MAX_BYTES = 5 * 1024 * 1024


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
    try:
        return max(1000, int(os.getenv("WEB_FETCH_TEXT_MAX", str(DEFAULT_TEXT_MAX))))
    except (TypeError, ValueError):
        return DEFAULT_TEXT_MAX


def _get_max_bytes(fetch_config: dict | None = None) -> int:
    if fetch_config and fetch_config.get("max_bytes") is not None:
        try:
            return max(1024, int(fetch_config["max_bytes"]))
        except (TypeError, ValueError):
            pass
    try:
        return max(1024, int(os.getenv("WEB_FETCH_MAX_BYTES", str(DEFAULT_MAX_BYTES))))
    except (TypeError, ValueError):
        return DEFAULT_MAX_BYTES


def _get_proxy(fetch_config: dict | None = None) -> str | None:
    if fetch_config and fetch_config.get("proxy"):
        return str(fetch_config["proxy"]).strip() or None
    return os.getenv("WEB_FETCH_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None


def _raw_to_fetch_dict(raw: WebFetchRaw, text_max: int) -> Dict[str, Any]:
    """将 WebFetchRaw 转为 backend 合同 dict：url, status_code, content_type, text(=extracted_text), truncated, title, extraction_method。"""
    content_type = (raw.headers.get("content-type") or "").strip()
    try:
        raw_text = raw.body_bytes.decode("utf-8", errors="replace")
    except Exception:
        raw_text = ""
    if not _is_text_content_type(content_type):
        return {
            "url": raw.url,
            "final_url": raw.final_url,
            "status_code": raw.status_code,
            "content_type": content_type,
            "text": "",
            "truncated": raw.meta.get("truncated", False),
            "error": raw.error,
            "meta": dict(raw.meta),
        }
    if "html" in content_type.lower():
        extracted = extract_html(raw)
        text = extracted.get("text") or extracted.get("extracted_text") or ""
        title = extracted.get("title") or ""
        method = extracted.get("extraction_method") or "fallback"
        paragraphs_count = extracted.get("paragraphs_count")
    else:
        text = raw_text
        title = ""
        method = "fallback"
        paragraphs_count = None
    truncated = raw.meta.get("truncated", False) or len(text) > text_max
    if len(text) > text_max:
        text = text[:text_max]
    out = {
        "url": raw.url,
        "final_url": raw.final_url,
        "status_code": raw.status_code,
        "content_type": content_type,
        "text": text,
        "truncated": truncated,
        "error": raw.error,
        "meta": dict(raw.meta),
    }
    if title is not None:
        out["title"] = title
    out["extracted_text"] = text
    out["extraction_method"] = method
    if paragraphs_count is not None:
        out["paragraphs_count"] = paragraphs_count
    return out


class HttpxFetchBackend:
    """委托 webfetch client；仅 http(s)，SSRF/重试/max_bytes/代理；403/429/body blocked 抛对应错误码。"""

    backend_id: str = "httpx"

    def __init__(self, fetch_config: dict | None = None) -> None:
        self._fetch_config = fetch_config or {}

    def _client(self, timeout_ms: int) -> WebfetchClient:
        timeout_sec = max(1.0, timeout_ms / 1000.0)
        if self._fetch_config.get("timeout_ms") is not None:
            try:
                timeout_sec = max(1.0, int(self._fetch_config["timeout_ms"]) / 1000.0)
            except (TypeError, ValueError):
                pass
        user_agent = (self._fetch_config.get("user_agent") or USER_AGENT)
        if isinstance(user_agent, str):
            user_agent = user_agent.strip() or USER_AGENT
        else:
            user_agent = USER_AGENT
        return WebfetchClient(
            timeout_connect_sec=min(5.0, timeout_sec / 2),
            timeout_read_sec=timeout_sec,
            max_bytes=_get_max_bytes(self._fetch_config),
            proxy=_get_proxy(self._fetch_config),
            user_agent=user_agent,
        )

    def fetch(self, url: str, timeout_ms: int) -> Dict[str, Any]:
        if not _is_http_or_https(url):
            raise WebInvalidInputError("url must be http:// or https://")
        url = url.strip()
        client = self._client(timeout_ms)
        raw = client.fetch(url)
        if raw.status_code in (403, 429):
            raise WebBlockedError(f"HTTP {raw.status_code}")
        if raw.error == "timeout_read":
            raise WebTimeoutError("Request timeout")
        if raw.error in ("network_unreachable", "connect_failed"):
            raise WebNetworkError(str(raw.error)[:500])
        try:
            raw_text = raw.body_bytes.decode("utf-8", errors="replace")
        except Exception:
            raw_text = ""
        if _body_indicates_blocked(raw_text):
            raise WebBlockedError("Page indicates block or captcha")
        text_max = _get_text_max()
        return _raw_to_fetch_dict(raw, text_max)
