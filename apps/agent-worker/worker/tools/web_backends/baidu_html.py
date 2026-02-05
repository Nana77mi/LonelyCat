"""BaiduHtmlBackend: 百度 HTML 搜索后端，无 key；解析用 baidu_parser。仅负责 search，不解析 /link?url= 落地页。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from worker.tools.web_backends.baidu_parser import parse_baidu_html
from worker.tools.web_backends.errors import (
    WebBlockedError,
    WebNetworkError,
    WebTimeoutError,
)

BAIDU_SEARCH_URL = "https://www.baidu.com/s"
USER_AGENT = "Mozilla/5.0 (compatible; LonelyCat/1.0; +https://github.com/lonelycat)"


class BaiduHtmlSearchBackend:
    """百度 HTML 后端：GET www.baidu.com/s?wd=，解析结果；无 key。复用 web.fetch 的 timeout/proxy/user_agent。"""

    backend_id: str = "baidu_html"

    def __init__(
        self,
        timeout_ms: int = 15000,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self._timeout_ms = max(1000, timeout_ms)
        self._proxy = (proxy or "").strip() or None
        self._user_agent = (user_agent or USER_AGENT).strip() or USER_AGENT

    def search(self, query: str, max_results: int, timeout_ms: int) -> List[Dict[str, Any]]:
        """请求百度 HTML 并解析；403/429 用 status_code 判定；验证码用 parser 返回的 captcha_required。"""
        timeout_sec = max(1, timeout_ms / 1000.0)
        # wd=query, rn=每页条数, pn=偏移（0 为第一页）
        url = BAIDU_SEARCH_URL + "?wd=" + quote(query.strip()) + "&rn=" + str(max(1, min(max_results, 10)))
        headers = {"User-Agent": self._user_agent}
        try:
            with httpx.Client(timeout=timeout_sec, proxy=self._proxy) as client:
                resp = client.get(url, headers=headers)
        except httpx.TimeoutException as e:
            raise WebTimeoutError(str(e)[:500]) from e
        except httpx.RequestError as e:
            raise WebNetworkError(str(e)[:500]) from e

        if resp.status_code == 403:
            raise WebBlockedError(f"HTTP 403", detail_code="http_403")
        if resp.status_code == 429:
            raise WebBlockedError(f"HTTP 429", detail_code="http_429")

        items, err = parse_baidu_html(resp.text)
        if err == "captcha_required":
            raise WebBlockedError("Page indicates captcha or security check", detail_code="captcha_required")
        if err == "parse_failed" or not items:
            return []
        return items[: max(1, min(max_results, 10))]
