"""Web search backends: protocol, stub, ddg_html, baidu_html, searxng, bocha, fetch_stub, http_fetch, errors."""

from worker.tools.web_backends.base import WebFetchBackend, WebSearchBackend
from worker.tools.web_backends.baidu_html import BaiduHtmlSearchBackend
from worker.tools.web_backends.bocha import BochaBackend
from worker.tools.web_backends.ddg_html import DDGHtmlBackend
from worker.tools.web_backends.fetch_stub import StubWebFetchBackend
from worker.tools.web_backends.http_fetch import HttpxFetchBackend
from worker.tools.web_backends.errors import (
    WebAuthError,
    WebBadGatewayError,
    WebBlockedError,
    WebInvalidInputError,
    WebNetworkError,
    WebParseError,
    WebProviderError,
    WebTimeoutError,
)
from worker.tools.web_backends.router import WebSearchRouter
from worker.tools.web_backends.searxng import SearxngBackend
from worker.tools.web_backends.stub import StubWebSearchBackend

__all__ = [
    "WebSearchBackend",
    "WebFetchBackend",
    "StubWebFetchBackend",
    "HttpxFetchBackend",
    "WebInvalidInputError",
    "WebProviderError",
    "WebTimeoutError",
    "WebBlockedError",
    "WebParseError",
    "WebNetworkError",
    "WebAuthError",
    "WebBadGatewayError",
    "StubWebSearchBackend",
    "BaiduHtmlSearchBackend",
    "BochaBackend",
    "DDGHtmlBackend",
    "SearxngBackend",
    "WebSearchRouter",
]
