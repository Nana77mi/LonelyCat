"""Tests for WebProvider: list_tools, invoke, input validation, unknown tool (no network)."""

from unittest.mock import Mock

import pytest

from worker.tools.web_backends.errors import WebInvalidInputError, WebProviderError
from worker.tools.web_backends.fetch_stub import StubWebFetchBackend
from worker.tools.web_backends.stub import StubWebSearchBackend
from worker.tools.web_provider import (
    WEB_SEARCH_INPUT_SCHEMA,
    TITLE_MAX,
    SNIPPET_MAX,
    WebProvider,
    normalize_search_items,
    truncate_fields,
)


def test_web_provider_list_tools_exposes_web_search_meta():
    """list_tools() 含 web.search 与 web.fetch；web.search 的 risk_level=read_only；input_schema 含 query/max_results；timeout_ms 有默认值。"""
    provider = WebProvider(
        search_backend=StubWebSearchBackend(),
        fetch_backend=StubWebFetchBackend(),
    )
    tools = provider.list_tools()
    assert len(tools) == 2
    names = [t.name for t in tools]
    assert "web.search" in names
    assert "web.fetch" in names
    t = next(x for x in tools if x.name == "web.search")
    assert t.risk_level == "read_only"
    assert t.input_schema == WEB_SEARCH_INPUT_SCHEMA
    assert "query" in t.input_schema.get("properties", {})
    assert "max_results" in t.input_schema.get("properties", {})
    assert t.timeout_ms is not None
    assert t.timeout_ms >= 1000
    assert t.capability_level == "L0"
    assert t.requires_confirm is False


def test_web_provider_invoke_returns_items_with_provider_and_truncation():
    """StubWebSearchBackend 返回结果；invoke 返回 {"items": [...]}，每项含 title/url/snippet/provider；超长字段被截断。"""
    class FakeBackendLong:
        backend_id = "stub"

        def search(self, query, max_results, timeout_ms):
            return [
                {"title": "x" * (TITLE_MAX + 10), "url": "https://a.com", "snippet": "y" * (SNIPPET_MAX + 10), "provider": "stub"},
                {"title": "B", "url": "https://b.com", "snippet": "s2"},
            ]

    provider = WebProvider(
        search_backend=FakeBackendLong(),
        fetch_backend=StubWebFetchBackend(),
    )
    ctx = Mock()
    result = provider.invoke("web.search", {"query": "x", "max_results": 2}, ctx)
    assert isinstance(result, dict)
    assert "items" in result
    items = result["items"]
    assert len(items) == 2
    for it in items:
        assert "title" in it and "url" in it and "snippet" in it and "provider" in it
        assert it["provider"] == "stub"
    assert len(items[0]["title"]) <= TITLE_MAX
    assert len(items[0]["snippet"]) <= SNIPPET_MAX


def test_web_provider_invoke_rejects_empty_query_invalid_input():
    """query 为空或仅空格时抛 WebInvalidInputError 且 code=InvalidInput。"""
    provider = WebProvider(
        search_backend=StubWebSearchBackend(),
        fetch_backend=StubWebFetchBackend(),
    )
    ctx = Mock()
    with pytest.raises(WebInvalidInputError) as exc_info:
        provider.invoke("web.search", {"query": ""}, ctx)
    assert exc_info.value.code == "InvalidInput"
    with pytest.raises(WebInvalidInputError) as exc_info2:
        provider.invoke("web.search", {"query": "   "}, ctx)
    assert exc_info2.value.code == "InvalidInput"


def test_web_provider_invoke_rejects_max_results_out_of_range():
    """max_results=0 或 999 时抛 InvalidInput。"""
    provider = WebProvider(
        search_backend=StubWebSearchBackend(),
        fetch_backend=StubWebFetchBackend(),
    )
    ctx = Mock()
    with pytest.raises(WebInvalidInputError) as exc_info:
        provider.invoke("web.search", {"query": "x", "max_results": 0}, ctx)
    assert exc_info.value.code == "InvalidInput"
    with pytest.raises(WebInvalidInputError) as exc_info2:
        provider.invoke("web.search", {"query": "x", "max_results": 999}, ctx)
    assert exc_info2.value.code == "InvalidInput"


def test_web_provider_invoke_unknown_tool_raises_tool_not_found():
    """invoke 未知工具名时抛 ToolNotFoundError。"""
    from worker.tools.errors import ToolNotFoundError

    provider = WebProvider(
        search_backend=StubWebSearchBackend(),
        fetch_backend=StubWebFetchBackend(),
    )
    ctx = Mock()
    with pytest.raises(ToolNotFoundError, match="web.other"):
        provider.invoke("web.other", {"query": "x"}, ctx)


def test_normalize_search_items_and_truncate_fields():
    """normalize_search_items 补全 provider；无有效 url 的项被丢弃；truncate_fields 按常量截断。"""
    raw = [{"title": "T", "url": "https://u"}, {"title": "T2", "snippet": "S2"}]  # 第二项无 url，丢弃
    norm = normalize_search_items(raw, "my_backend")
    assert len(norm) == 1
    assert norm[0]["provider"] == "my_backend"
    assert norm[0]["url"] == "https://u"
    assert norm[0]["snippet"] == ""
    out = truncate_fields(norm[0])
    assert out["title"] == "T"
    assert out["url"] == "https://u"
    assert len(out["snippet"]) == 0
    assert out["provider"] == "my_backend"


def test_normalize_filters_items_without_url():
    """url 为空、非字符串、非 http(s) 的项被丢弃；title/snippet 非 str 转 str。"""
    raw = [
        {"title": "OK", "url": "https://a.com", "snippet": "s1"},
        {"title": "NoUrl", "url": "", "snippet": "s2"},
        {"title": "BadScheme", "url": "ftp://x.com", "snippet": "s3"},
        {"title": 123, "url": "https://b.com", "snippet": 456},
    ]
    norm = normalize_search_items(raw, "backend")
    assert len(norm) == 2
    assert norm[0]["title"] == "OK"
    assert norm[0]["url"] == "https://a.com"
    assert norm[1]["title"] == "123"
    assert norm[1]["snippet"] == "456"


def test_normalize_and_truncate_preserve_rank_sequence_after_slice():
    """任意 backend 的 items 超过 max_results 时，normalize+truncate 后取前 N 条，rank 为连续 1..N 且为 int。"""
    raw = [
        {"title": f"T{i}", "url": f"https://example.com/p{i}", "snippet": ""}
        for i in range(5)
    ]
    norm = normalize_search_items(raw, "any_backend")
    assert len(norm) == 5
    truncated = [truncate_fields(it) for it in norm]
    max_results = 2
    taken = truncated[:max_results]
    assert len(taken) == max_results
    for idx, it in enumerate(taken):
        assert it.get("rank") == idx + 1
        assert isinstance(it["rank"], int)
