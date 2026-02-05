"""SearxngBackend: SearXNG JSON API 后端，需用户自备实例（SEARXNG_BASE_URL）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from worker.tools.web_backends.errors import (
    WebAuthError,
    WebBadGatewayError,
    WebNetworkError,
    WebParseError,
    WebTimeoutError,
)

PROVIDER_MAX = 64


def _parse_searxng_json(data: Any) -> List[Dict[str, Any]]:
    """解析 SearXNG JSON 响应；results 每项映射 title/url/snippet/provider；结构异常抛 WebParseError。"""
    if not isinstance(data, dict):
        raise WebParseError("Response is not a JSON object")
    results = data.get("results")
    if not isinstance(results, list):
        raise WebParseError("Missing or invalid 'results' array")
    out: List[Dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url_val = item.get("url")
        if not url_val or not isinstance(url_val, str) or not (
            url_val.strip().startswith("http://") or url_val.strip().startswith("https://")
        ):
            continue
        title_val = item.get("title")
        if title_val is not None and not isinstance(title_val, str):
            title_val = str(title_val)
        content_val = item.get("content")
        if content_val is not None and not isinstance(content_val, str):
            content_val = str(content_val)
        engine_val = item.get("engine")
        if engine_val is not None and not isinstance(engine_val, str):
            engine_val = str(engine_val)
        provider = (engine_val or "searxng").strip()[:PROVIDER_MAX]
        out.append({
            "title": (title_val or "").strip(),
            "url": (url_val or "").strip(),
            "snippet": (content_val or "").strip(),
            "provider": provider,
        })
    return out


class SearxngBackend:
    """SearXNG JSON API 后端：GET base_url/search?q=...&format=json，解析 results。"""

    backend_id: str = "searxng"

    def __init__(
        self,
        base_url: str,
        engine: Optional[str] = None,
        categories: Optional[str] = None,
        language: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._engine = engine
        self._categories = categories
        self._language = language
        self._api_key = api_key

    def search(
        self,
        query: str,
        max_results: int,
        timeout_ms: int,
        *,
        remaining_budget_ms: Optional[int] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """请求 SearXNG JSON API；超时/401/5xx/解析失败抛对应错误码。"""
        timeout_sec = max(1, timeout_ms / 1000.0)
        url = f"{self._base_url}/search"
        params: Dict[str, str] = {
            "q": query.strip(),
            "format": "json",
        }
        if self._engine:
            params["engines"] = self._engine
        if self._categories:
            params["categories"] = self._categories
        if self._language:
            params["language"] = self._language
        headers: Dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            with httpx.Client(timeout=timeout_sec) as client:
                resp = client.get(url, params=params, headers=headers or None)
        except httpx.TimeoutException as e:
            raise WebTimeoutError(str(e)[:500]) from e
        except httpx.RequestError as e:
            raise WebNetworkError(str(e)[:500]) from e

        if resp.status_code in (401, 403):
            raise WebAuthError(f"HTTP {resp.status_code}")
        if 500 <= resp.status_code < 600:
            raise WebBadGatewayError(f"HTTP {resp.status_code}")

        try:
            data = resp.json()
        except (ValueError, TypeError) as e:
            raise WebParseError(str(e)[:500]) from e

        try:
            items = _parse_searxng_json(data)
        except WebParseError:
            raise
        except Exception as e:
            raise WebParseError(str(e)[:500]) from e

        return items[: max(1, min(max_results, 10))]
