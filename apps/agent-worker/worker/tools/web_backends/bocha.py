"""BochaBackend: Bocha Web Search API 后端，需 BOCHA_API_KEY；POST /v1/web-search，Authorization: Bearer。"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from worker.tools.web_backends.errors import (
    WebAuthError,
    WebBadGatewayError,
    WebBlockedError,
    WebNetworkError,
    WebParseError,
    WebTimeoutError,
)

logger = logging.getLogger(__name__)

# 官方默认 base_url（可被配置覆盖）
BOCHA_DEFAULT_BASE_URL = "https://api.bochaai.com"


def _is_valid_url(url: Any) -> bool:
    if url is None or not isinstance(url, str):
        return False
    u = url.strip()
    return bool(u and (u.startswith("http://") or u.startswith("https://")))


def _extract_web_search_results_array(payload: dict) -> Optional[List]:
    """从 Bocha 响应中提取网页结果数组（Bing 兼容结构优先）。
    优先级：webPages.value（官方） -> data.webPages.value -> results -> citations -> data.results/list/items。"""
    # 1) 官方路径：Bing 兼容 webPages.value
    web_pages = payload.get("webPages")
    if isinstance(web_pages, dict):
        val = web_pages.get("value")
        if isinstance(val, list):
            return val
    # 2) data 包一层：data.webPages.value
    data = payload.get("data")
    if isinstance(data, dict):
        web_pages = data.get("webPages")
        if isinstance(web_pages, dict):
            val = web_pages.get("value")
            if isinstance(val, list):
                return val
        # data.results / data.list / data.items 兼容
        for key in ("results", "list", "items"):
            val = data.get(key)
            if isinstance(val, list):
                return val
    # 3) 兼容旧/非官方返回：顶层 results / citations
    for key in ("results", "citations"):
        val = payload.get(key)
        if isinstance(val, list):
            return val
    return None


def _item_from_bocha_value(item: dict) -> Optional[Dict[str, Any]]:
    """将单条 Bocha/Bing 兼容项映射为统一 schema：title/url/snippet/provider；可选 published_at、meta(siteName, siteIcon)。"""
    if not isinstance(item, dict):
        return None
    url_val = item.get("url") or item.get("link") or item.get("href")
    if not _is_valid_url(url_val):
        return None
    # Bing 兼容：name 为标题
    title_val = item.get("name") or item.get("title")
    if title_val is not None and not isinstance(title_val, str):
        title_val = str(title_val)
    snippet_val = (
        item.get("snippet")
        or item.get("summary")
        or item.get("description")
        or item.get("content")
        or item.get("text")
    )
    if snippet_val is not None and not isinstance(snippet_val, str):
        snippet_val = str(snippet_val)
    row: Dict[str, Any] = {
        "title": (title_val or "").strip(),
        "url": (url_val or "").strip(),
        "snippet": (snippet_val or "").strip(),
        "provider": "bocha",
    }
    date_pub = item.get("datePublished")
    if isinstance(date_pub, str) and date_pub.strip():
        row["published_at"] = date_pub.strip()
    site_name = item.get("siteName")
    site_icon = item.get("siteIcon")
    if site_name is not None or site_icon is not None:
        row["meta"] = {}
        if site_name is not None:
            row["meta"]["siteName"] = str(site_name).strip() if site_name else ""
        if site_icon is not None and isinstance(site_icon, str) and _is_valid_url(site_icon):
            row["meta"]["siteIcon"] = site_icon.strip()
    return row


def _parse_bocha_normalized_response(
    data: Any,
    *,
    include_raw_for_debug: bool = False,
) -> Dict[str, Any]:
    """解析 Bocha 响应为 normalized_response：items + summary? + raw_provider_payload?(debug)。
    官方为 Bing 兼容结构：webPages.value；兼容 data.webPages.value、results、citations。"""
    if not isinstance(data, dict):
        raise WebParseError("Response is not a JSON object")
    summary: Optional[str] = None
    raw_summary = data.get("summary")
    if isinstance(raw_summary, str):
        summary = raw_summary.strip()
    elif raw_summary is not None and not isinstance(raw_summary, str):
        summary = str(raw_summary).strip()
    raw_list = _extract_web_search_results_array(data)
    if raw_list is None:
        keys_preview = list(data.keys())[:10]
        logger.warning(
            "bocha parse failed provider=bocha response_keys=%s",
            keys_preview,
        )
        raise WebParseError(
            "Missing or invalid webPages.value/results/citations; response keys: %s" % keys_preview
        )
    items: List[Dict[str, Any]] = []
    for raw_item in raw_list:
        row = _item_from_bocha_value(raw_item)
        if row is not None:
            items.append(row)
    normalized: Dict[str, Any] = {
        "items": items,
    }
    if summary:
        normalized["summary"] = summary
    if include_raw_for_debug:
        normalized["raw_provider_payload"] = data
    return normalized


class BochaBackend:
    """Bocha Web Search API 后端：POST base_url/v1/web-search，Authorization: Bearer api_key。"""

    backend_id: str = "bocha"

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout_ms: Optional[int] = None,
        top_k_default: int = 5,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._base_url = (base_url or BOCHA_DEFAULT_BASE_URL).rstrip("/")
        self._timeout_ms = max(1000, int(timeout_ms or 15000))
        self._top_k_default = max(1, min(10, top_k_default))

    def search(
        self,
        query: str,
        max_results: int,
        timeout_ms: int,
        *,
        remaining_budget_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """请求 Bocha /v1/web-search；返回 normalized_response { items, summary?, raw_provider_payload? }。
        仅对 Timeout/NetworkError/5xx 重试，不对 AuthError/429 重试。"""
        if not self._api_key:
            raise WebAuthError("Bocha API key is required")
        if remaining_budget_ms is not None and remaining_budget_ms <= 0:
            logger.info("bocha search skipped provider=bocha reason=remaining_budget_ms<=0")
            return {"items": []}
        effective_timeout_ms = max(1000, timeout_ms) if timeout_ms else self._timeout_ms
        timeout_sec = max(1, effective_timeout_ms / 1000.0)
        url = f"{self._base_url}/v1/web-search"
        payload: Dict[str, Any] = {
            "query": query.strip(),
            "count": max(1, min(max_results, 10)),
        }
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        last_error: Optional[Exception] = None
        for attempt in range(2):
            try:
                t0 = time.monotonic()
                with httpx.Client(timeout=timeout_sec) as client:
                    resp = client.post(url, json=payload, headers=headers)
                latency_ms = int((time.monotonic() - t0) * 1000)
                if resp.status_code in (401, 403):
                    logger.warning(
                        "bocha search auth failure provider=bocha error_type=AuthError status=%s latency_ms=%s",
                        resp.status_code,
                        latency_ms,
                    )
                    raise WebAuthError(f"HTTP {resp.status_code}")
                if resp.status_code == 429:
                    logger.warning(
                        "bocha search rate limited provider=bocha error_type=WebBlocked status=429 latency_ms=%s",
                        latency_ms,
                    )
                    raise WebBlockedError("HTTP 429", detail_code="http_429")
                if 500 <= resp.status_code < 600:
                    logger.warning(
                        "bocha search upstream error provider=bocha error_type=BadGateway status=%s latency_ms=%s",
                        resp.status_code,
                        latency_ms,
                    )
                    if attempt == 0:
                        last_error = WebBadGatewayError(f"HTTP {resp.status_code}")
                        continue
                    raise last_error
                try:
                    data = resp.json()
                except (ValueError, TypeError) as e:
                    raise WebParseError(str(e)[:500]) from e
                normalized = _parse_bocha_normalized_response(data, include_raw_for_debug=False)
                items = normalized.get("items") or []
                request_id = None
                if isinstance(data, dict):
                    request_id = data.get("request_id") or data.get("requestId")
                    if request_id is not None and not isinstance(request_id, str):
                        request_id = str(request_id)
                if not items:
                    logger.info(
                        "bocha search empty result provider=bocha latency_ms=%s request_id=%s",
                        latency_ms,
                        request_id or "",
                    )
                    raise WebParseError("EmptyResult")
                logger.info(
                    "bocha search success provider=bocha latency_ms=%s items_count=%s request_id=%s",
                    latency_ms,
                    len(items),
                    request_id or "",
                )
                normalized["items"] = items[: max(1, min(max_results, 10))]
                return normalized
            except (WebAuthError, WebBlockedError, WebParseError):
                raise
            except httpx.TimeoutException as e:
                last_error = WebTimeoutError(str(e)[:500])
                logger.warning(
                    "bocha search timeout provider=bocha error_type=Timeout",
                    exc_info=False,
                )
                if attempt == 0:
                    continue
                raise last_error from e
            except httpx.RequestError as e:
                last_error = WebNetworkError(str(e)[:500])
                logger.warning(
                    "bocha search network error provider=bocha error_type=NetworkError",
                    exc_info=False,
                )
                if attempt == 0:
                    continue
                raise last_error from e
        if last_error is not None:
            raise last_error
        raise WebParseError("EmptyResult")
