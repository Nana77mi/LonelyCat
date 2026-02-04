"""WebProvider web.fetch: list_tools 含 web.fetch，invoke 返回 canonical 形状，invalid url 抛 InvalidInput。"""

from unittest.mock import Mock

import pytest

from worker.tools.web_backends.errors import WebInvalidInputError
from worker.tools.web_backends.fetch_stub import StubWebFetchBackend
from worker.tools.web_backends.stub import StubWebSearchBackend
from worker.tools.web_provider import WEB_FETCH_INPUT_SCHEMA, WebProvider


def test_web_provider_list_tools_includes_web_fetch_meta():
    """list_tools() 含 web.fetch；input_schema 含 url、可选 timeout_ms。"""
    provider = WebProvider(
        search_backend=StubWebSearchBackend(),
        fetch_backend=StubWebFetchBackend(),
    )
    tools = provider.list_tools()
    names = [t.name for t in tools]
    assert "web.fetch" in names
    fetch_meta = next(t for t in tools if t.name == "web.fetch")
    assert fetch_meta.input_schema == WEB_FETCH_INPUT_SCHEMA
    assert "url" in fetch_meta.input_schema.get("required", [])
    assert "url" in fetch_meta.input_schema.get("properties", {})


def test_web_provider_invoke_web_fetch_returns_canonical_shape():
    """invoke web.fetch 返回 dict 含 url/status_code/content_type/text/truncated。"""
    provider = WebProvider(
        search_backend=StubWebSearchBackend(),
        fetch_backend=StubWebFetchBackend(),
    )
    ctx = Mock()
    result = provider.invoke("web.fetch", {"url": "https://example.com/p"}, ctx)
    assert isinstance(result, dict)
    assert "url" in result
    assert "status_code" in result
    assert "content_type" in result
    assert "text" in result
    assert "truncated" in result
    assert result["url"] == "https://example.com/p"
    assert result["status_code"] == 200
    assert "Stub content" in result["text"]
    assert result["truncated"] is False


def test_web_provider_invoke_web_fetch_invalid_url_raises_invalid_input():
    """url 非 http(s) 时抛 WebInvalidInputError。"""
    provider = WebProvider(
        search_backend=StubWebSearchBackend(),
        fetch_backend=StubWebFetchBackend(),
    )
    ctx = Mock()
    with pytest.raises(WebInvalidInputError):
        provider.invoke("web.fetch", {"url": "ftp://x.com"}, ctx)
    with pytest.raises(WebInvalidInputError):
        provider.invoke("web.fetch", {"url": ""}, ctx)
