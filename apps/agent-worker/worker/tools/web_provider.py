"""WebProvider: ToolProvider 实现，对外暴露 web.search 与 web.fetch，通过 backend 执行。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from worker.task_context import TaskContext
from worker.tools.catalog import CAPABILITY_L0, ToolMeta
from worker.tools.errors import ToolNotFoundError
from worker.tools.web_backends.base import WebFetchBackend, WebSearchBackend
from worker.tools.web_backends.errors import WebInvalidInputError, WebProviderError

# 截断常量（与 runner/合同一致）
TITLE_MAX = 512
URL_MAX = 2048
SNIPPET_MAX = 4096
PROVIDER_MAX = 64

WEB_SEARCH_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
    },
    "required": ["query"],
}

WEB_FETCH_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "minLength": 1},
        "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 120000},
    },
    "required": ["url"],
}

DEFAULT_WEB_SEARCH_TIMEOUT_MS = 15_000
DEFAULT_WEB_FETCH_TIMEOUT_MS = 15_000
DEFAULT_MAX_RESULTS = 5


def _is_valid_search_url(url: Any) -> bool:
    """url 非空、为字符串且以 http:// 或 https:// 开头时返回 True，否则丢弃/过滤。"""
    if url is None:
        return False
    if not isinstance(url, str):
        return False
    u = url.strip()
    return bool(u and (u.startswith("http://") or u.startswith("https://")))


def _is_valid_fetch_url(url: Any) -> bool:
    """web.fetch 仅允许 http(s)。"""
    return _is_valid_search_url(url)


def normalize_fetch_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """将 backend 返回补齐为 canonical：url, status_code, content_type, text(=extracted_text), truncated；可选 title, extracted_text, extraction_method, final_url, cache_hit, artifact_paths。"""
    extracted = str(raw.get("text") or raw.get("extracted_text") or "")
    out = {
        "url": str(raw.get("url", "")).strip(),
        "status_code": int(raw.get("status_code", 0)) if raw.get("status_code") is not None else 0,
        "content_type": str(raw.get("content_type", "")).strip(),
        "text": extracted,
        "truncated": bool(raw.get("truncated", False)),
    }
    if raw.get("final_url") is not None:
        out["final_url"] = str(raw["final_url"]).strip()
    if raw.get("title") is not None:
        out["title"] = str(raw["title"]).strip()
    if raw.get("extracted_text") is not None:
        out["extracted_text"] = str(raw["extracted_text"])
    if raw.get("extraction_method") is not None:
        out["extraction_method"] = str(raw["extraction_method"])
    if raw.get("paragraphs_count") is not None:
        out["paragraphs_count"] = int(raw["paragraphs_count"])
    if raw.get("cache_hit") is not None:
        out["cache_hit"] = bool(raw["cache_hit"])
    if raw.get("artifact_paths") is not None:
        out["artifact_paths"] = dict(raw["artifact_paths"])
    return out


def normalize_search_items(raw_items: List[Dict[str, Any]], backend_id: str) -> List[Dict[str, Any]]:
    """保证每项有 title/url/snippet/provider/rank；url 为空/非字符串/非 http(s) 则丢弃；rank 仅在此层写入（1-based）。"""
    out: List[Dict[str, Any]] = []
    for i, item in enumerate(raw_items or []):
        if not isinstance(item, dict):
            continue
        url_val = item.get("url")
        if not _is_valid_search_url(url_val):
            continue
        title_val = item.get("title")
        snippet_val = item.get("snippet")
        if title_val is not None and not isinstance(title_val, str):
            title_val = str(title_val)
        if snippet_val is not None and not isinstance(snippet_val, str):
            snippet_val = str(snippet_val)
        row = {
            "title": title_val if title_val is not None else "",
            "url": (url_val or "").strip() if isinstance(url_val, str) else "",
            "snippet": snippet_val if snippet_val is not None else "",
            "provider": item.get("provider") or backend_id,
            "rank": i + 1,
        }
        out.append(row)
    return out


def truncate_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    """对 title/url/snippet/provider 按常量截断；保留 rank（若有），保证为 int。ddg_html/searxng/stub/baidu_html 均走此逻辑。"""
    out: Dict[str, Any] = {
        "title": (item.get("title") or "")[:TITLE_MAX],
        "url": (item.get("url") or "")[:URL_MAX],
        "snippet": (item.get("snippet") or "")[:SNIPPET_MAX],
        "provider": (item.get("provider") or "")[:PROVIDER_MAX],
    }
    rank_val = item.get("rank")
    if rank_val is not None:
        try:
            out["rank"] = int(rank_val)
        except (TypeError, ValueError):
            out["rank"] = rank_val
    return out


class WebProvider:
    """ToolProvider：提供 web.search 与 web.fetch，通过 search_backend / fetch_backend 执行。"""

    PROVIDER_ID = "web"

    def __init__(
        self,
        search_backend: WebSearchBackend,
        fetch_backend: WebFetchBackend,
        timeout_ms: int = DEFAULT_WEB_SEARCH_TIMEOUT_MS,
        fetch_timeout_ms: Optional[int] = None,
        default_max_results: int = DEFAULT_MAX_RESULTS,
    ) -> None:
        self._backend = search_backend
        self._fetch_backend = fetch_backend
        self._timeout_ms = timeout_ms
        self._fetch_timeout_ms = fetch_timeout_ms if fetch_timeout_ms is not None else timeout_ms
        self._default_max_results = default_max_results

    def list_tools(self) -> List[ToolMeta]:
        return [
            ToolMeta(
                name="web.search",
                input_schema=WEB_SEARCH_INPUT_SCHEMA,
                side_effects=False,
                risk_level="read_only",
                provider_id=self.PROVIDER_ID,
                capability_level=CAPABILITY_L0,
                requires_confirm=False,
                timeout_ms=self._timeout_ms,
            ),
            ToolMeta(
                name="web.fetch",
                input_schema=WEB_FETCH_INPUT_SCHEMA,
                side_effects=False,
                risk_level="read_only",
                provider_id=self.PROVIDER_ID,
                capability_level=CAPABILITY_L0,
                requires_confirm=False,
                timeout_ms=self._fetch_timeout_ms,
            ),
        ]

    def invoke(
        self,
        tool_name: str,
        args: Dict[str, Any],
        ctx: TaskContext,
        *,
        llm: Optional[Any] = None,
    ) -> Any:
        if tool_name == "web.search":
            return self._invoke_search(args)
        if tool_name == "web.fetch":
            return self._invoke_fetch(args, ctx)
        raise ToolNotFoundError(tool_name, "WebProvider only supports web.search and web.fetch")

    def _invoke_search(self, args: Dict[str, Any]) -> Any:
        query = args.get("query")
        if query is None:
            raise WebInvalidInputError("query is required")
        if not isinstance(query, str):
            raise WebInvalidInputError("query must be a string")
        query = query.strip()
        if not query:
            raise WebInvalidInputError("query must be non-empty")

        max_results = args.get("max_results")
        if max_results is None:
            max_results = self._default_max_results
        if not isinstance(max_results, int):
            try:
                max_results = int(max_results)
            except (TypeError, ValueError):
                raise WebInvalidInputError("max_results must be an integer")
        if max_results < 1 or max_results > 10:
            raise WebInvalidInputError("max_results must be between 1 and 10")

        try:
            raw_items = self._backend.search(query, max_results, self._timeout_ms)
        except (OSError, FileNotFoundError) as e:
            msg = str(e)[:500]
            if "Errno 2" in msg or "No such file or directory" in msg:
                hint = " (On Windows, unset SSL_CERT_FILE/REQUESTS_CA_BUNDLE if set to a Unix path, or use web.search.backend=stub.)"
                raise WebProviderError(msg + hint) from e
            raise WebProviderError(msg) from e
        except Exception as e:
            if getattr(e, "code", None):
                raise
            raise WebProviderError(str(e)[:500]) from e

        normalized = normalize_search_items(raw_items, self._backend.backend_id)
        truncated = [truncate_fields(it) for it in normalized]
        return {"items": truncated}

    def _invoke_fetch(self, args: Dict[str, Any], ctx: Optional[TaskContext] = None) -> Any:
        url = args.get("url")
        if url is None:
            raise WebInvalidInputError("url is required")
        if not isinstance(url, str):
            raise WebInvalidInputError("url must be a string")
        url = url.strip()
        if not url:
            raise WebInvalidInputError("url must be non-empty")
        if not _is_valid_fetch_url(url):
            raise WebInvalidInputError("url must be http:// or https://")
        timeout_ms = args.get("timeout_ms")
        if timeout_ms is None:
            timeout_ms = self._fetch_timeout_ms
        if not isinstance(timeout_ms, int):
            try:
                timeout_ms = int(timeout_ms)
            except (TypeError, ValueError):
                raise WebInvalidInputError("timeout_ms must be an integer")
        if timeout_ms < 1000 or timeout_ms > 120000:
            timeout_ms = self._fetch_timeout_ms
        artifact_dir = getattr(ctx, "artifact_dir", None) if ctx else None
        try:
            raw = self._fetch_backend.fetch(url, timeout_ms, artifact_dir=artifact_dir)
        except TypeError:
            raw = self._fetch_backend.fetch(url, timeout_ms)
        except Exception as e:
            if getattr(e, "code", None):
                raise
            raise WebProviderError(str(e)[:500]) from e
        return normalize_fetch_result(raw)
