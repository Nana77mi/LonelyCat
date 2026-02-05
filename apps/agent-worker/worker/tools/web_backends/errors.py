"""Web search backend / WebProvider 错误码（合同稳定，供 step.error_code）。"""

from __future__ import annotations

from typing import Any, Dict, Optional


class WebInvalidInputError(ValueError):
    """输入校验失败（空 query、max_results 越界等）；error.code = InvalidInput。"""

    code: str = "InvalidInput"

    def __init__(self, message: str = "") -> None:
        self.detail = message
        super().__init__(message or "Invalid input")


class WebProviderError(ValueError):
    """Backend 抛出异常时由 WebProvider wrap；error.code = WebProviderError。"""

    code: str = "WebProviderError"

    def __init__(self, message: str = "") -> None:
        self.detail = message
        super().__init__(message or "Web provider error")


class WebTimeoutError(ValueError):
    """请求超时；error.code = Timeout。"""

    code: str = "Timeout"

    def __init__(self, message: str = "") -> None:
        self.detail = message
        super().__init__(message or "Request timeout")


class WebBlockedError(ValueError):
    """403/429/captcha/页面提示被挡；error.code = WebBlocked；可选 detail_code 供 step.meta 与 debug bundle 展示。
    可选 serp_html/serp_meta 供 runner 落盘（与 WebParseError 一致），便于排查。"""

    code: str = "WebBlocked"

    def __init__(
        self,
        message: str = "",
        detail_code: Optional[str] = None,
        *,
        serp_html: Optional[str] = None,
        serp_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.detail = message
        self.detail_code: Optional[str] = detail_code  # e.g. captcha_required, http_403, http_429
        self.serp_html: Optional[str] = serp_html
        self.serp_meta: Optional[Dict[str, Any]] = serp_meta
        super().__init__(message or "Request blocked")


class WebParseError(ValueError):
    """HTML 结构不匹配/解析不到结果；error.code = WebParseError。
    可选 serp_html / serp_meta 供 runner 落盘为 search/serp.html 与 search/serp.meta.json。
    """

    code: str = "WebParseError"

    def __init__(
        self,
        message: str = "",
        *,
        serp_html: Optional[str] = None,
        serp_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.detail = message
        self.serp_html: Optional[str] = serp_html
        self.serp_meta: Optional[Dict[str, Any]] = serp_meta
        super().__init__(message or "Parse error")


class WebNetworkError(ValueError):
    """DNS/连接失败；error.code = NetworkError。"""

    code: str = "NetworkError"

    def __init__(self, message: str = "") -> None:
        self.detail = message
        super().__init__(message or "Network error")


class WebAuthError(ValueError):
    """401/403 或缺少 API key；error.code = AuthError。"""

    code: str = "AuthError"

    def __init__(self, message: str = "") -> None:
        self.detail = message
        super().__init__(message or "Auth error")


class WebBadGatewayError(ValueError):
    """5xx/上游不可用；error.code = BadGateway。"""

    code: str = "BadGateway"

    def __init__(self, message: str = "") -> None:
        self.detail = message
        super().__init__(message or "Bad gateway")


class WebSSRFBlockedError(ValueError):
    """URL 解析到私网/环回/链路本地；error.code = ssrf_blocked。"""

    code: str = "ssrf_blocked"

    def __init__(self, message: str = "") -> None:
        self.detail = message
        super().__init__(message or "SSRF blocked")
