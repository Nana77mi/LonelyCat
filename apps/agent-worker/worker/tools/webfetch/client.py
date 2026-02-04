"""webfetch 客户端：httpx GET + SSRF/URL 规范化/重试/max_bytes/代理。"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import httpx

from worker.tools.web_backends.errors import (
    WebInvalidInputError,
    WebSSRFBlockedError,
)
from worker.tools.webfetch.models import WebFetchRaw
from worker.tools.webfetch.ssrf import check_ssrf_blocked
from worker.tools.webfetch.url_utils import normalize_fetch_url

USER_AGENT = "Mozilla/5.0 (compatible; LonelyCat/1.0; +https://github.com/lonelycat)"
ACCEPT_LANGUAGE = "en-US,en;q=0.9"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
MAX_RETRIES = 3
RETRY_STATUSES = (429,) + tuple(range(500, 600))


def _is_http_or_https(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    return u.startswith("http://") or u.startswith("https://")


class WebfetchClient:
    """单次/重试 GET，返回 WebFetchRaw；含 SSRF、URL 规范化、max_bytes、代理。"""

    def __init__(
        self,
        timeout_connect_sec: float = 5.0,
        timeout_read_sec: float = 20.0,
        max_bytes: int = DEFAULT_MAX_BYTES,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self.timeout_connect_sec = timeout_connect_sec
        self.timeout_read_sec = timeout_read_sec
        self.max_bytes = max(1024, max_bytes)
        self.proxy = proxy
        self.user_agent = user_agent or USER_AGENT

    def fetch(self, url: str) -> WebFetchRaw:
        """规范化 URL、SSRF 检查、重试（仅 429/5xx/timeout），返回 WebFetchRaw。"""
        if not _is_http_or_https(url):
            raise WebInvalidInputError("url must be http:// or https://")
        url = url.strip()
        url = normalize_fetch_url(url)
        check_ssrf_blocked(url)

        last_exc: Optional[Exception] = None
        last_resp: Optional[httpx.Response] = None
        last_body: Optional[bytes] = None
        for attempt in range(MAX_RETRIES):
            try:
                resp, body = self._do_request(url)
                last_resp = resp
                last_body = body
                if resp.status_code in RETRY_STATUSES and attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                return self._build_raw(url, resp, body, error=None)
            except httpx.TimeoutException as e:
                last_exc = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                return self._build_raw(
                    url,
                    httpx.Response(408, request=httpx.Request("GET", url)),
                    b"",
                    error="timeout_read",
                )
            except httpx.RequestError as e:
                last_exc = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                code = "network_unreachable" if "unreachable" in str(e).lower() or "101" in str(e) else "connect_failed"
                return self._build_raw(
                    url,
                    httpx.Response(0, request=httpx.Request("GET", url)),
                    b"",
                    error=code,
                )
        if last_resp is not None and last_body is not None:
            return self._build_raw(url, last_resp, last_body, error=self._error_for_status(last_resp.status_code))
        if last_exc:
            raise last_exc
        return self._build_raw(
            url,
            httpx.Response(0, request=httpx.Request("GET", url)),
            b"",
            error="connect_failed",
        )

    def _do_request(self, url: str) -> Tuple[httpx.Response, bytes]:
        """单次 GET，stream 读取至多 max_bytes。"""
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": ACCEPT_LANGUAGE,
        }
        timeout = httpx.Timeout(self.timeout_connect_sec, read=self.timeout_read_sec)
        with httpx.Client(timeout=timeout, proxy=self.proxy, headers=headers) as client:
            resp = client.get(url)
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total <= self.max_bytes:
                    chunks.append(chunk)
                else:
                    remainder = self.max_bytes - (total - len(chunk))
                    if remainder > 0:
                        chunks.append(chunk[:remainder])
                    break
            body = b"".join(chunks)
        return resp, body

    def _error_for_status(self, status: int) -> str:
        if status == 403:
            return "http_403"
        if status == 429:
            return "http_429"
        if 500 <= status < 600:
            return "connect_failed"
        return ""

    def _build_raw(
        self,
        url: str,
        resp: httpx.Response,
        body: bytes,
        error: Optional[str],
    ) -> WebFetchRaw:
        final_url = str(resp.url) if resp.url else url
        content_length_h = resp.headers.get("content-length")
        content_length = int(content_length_h) if content_length_h and content_length_h.isdigit() else None
        truncated = len(body) >= self.max_bytes and (content_length is None or content_length > self.max_bytes)
        if error is None and resp.status_code in (403, 429):
            error = self._error_for_status(resp.status_code)
        meta: Dict[str, Any] = {
            "bytes_read": len(body),
            "truncated": truncated,
        }
        if content_length is not None:
            meta["content_length"] = content_length
        return WebFetchRaw(
            url=url,
            final_url=final_url,
            status_code=resp.status_code,
            headers=dict(resp.headers),
            body_bytes=body,
            error=error,
            meta=meta,
        )
