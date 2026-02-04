"""Web search backends: protocol, stub, ddg_html, searxng, fetch_stub, http_fetch, errors."""

from worker.tools.web_backends.base import WebFetchBackend, WebSearchBackend
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
    "DDGHtmlBackend",
    "SearxngBackend",
]
