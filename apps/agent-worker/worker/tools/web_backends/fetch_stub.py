"""Stub WebFetchBackend：不打网，返回固定 canonical 形状。"""

from __future__ import annotations

from typing import Any, Dict

from worker.tools.web_backends.errors import WebInvalidInputError


def _is_http_or_https(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    return u.startswith("http://") or u.startswith("https://")


class StubWebFetchBackend:
    """Stub fetch backend：fetch() 返回固定 canonical，仅允许 http(s) URL。"""

    backend_id: str = "stub"

    def fetch(self, url: str, timeout_ms: int) -> Dict[str, Any]:
        if not _is_http_or_https(url):
            raise WebInvalidInputError("url must be http:// or https://")
        u = (url or "").strip()
        return {
            "url": u,
            "status_code": 200,
            "content_type": "text/html",
            "text": f"Stub content for {u}",
            "truncated": False,
        }
