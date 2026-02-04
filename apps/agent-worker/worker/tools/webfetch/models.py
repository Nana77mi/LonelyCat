"""WebFetchRaw / WebFetchResult 数据模型与 error 枚举（webfetch 合同）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# 细粒度 error 枚举（供 step.error_code、debug bundle、UI 展示）
WEB_FETCH_ERROR_CODES = (
    "dns_failed",
    "connect_failed",
    "tls_failed",
    "timeout_connect",
    "timeout_read",
    "http_403",
    "http_429",
    "content_too_large",
    "ssrf_blocked",
    "parse_failed",
    "network_unreachable",
    "unsupported_content_type",
)


@dataclass
class WebFetchRaw:
    """Fetcher 层输出：status, headers, body_bytes, final_url, error_code, meta（bytes_read 等）。"""

    url: str
    final_url: str
    status_code: int
    headers: Dict[str, str]
    body_bytes: bytes
    error: Optional[str] = None  # 见 WEB_FETCH_ERROR_CODES
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_canonical_dict(self) -> Dict[str, Any]:
        """转为与现有 web.fetch 合同兼容的 dict（url, status_code, content_type, text, truncated）。"""
        content_type = (self.headers.get("content-type") or "").strip()
        try:
            text = self.body_bytes.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        truncated = self.meta.get("truncated", False)
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "content_type": content_type,
            "text": text,
            "truncated": truncated,
            "error": self.error,
            "meta": dict(self.meta),
        }
