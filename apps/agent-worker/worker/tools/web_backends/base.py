"""WebSearchBackend 协议：backend 只负责“搜到原始结果”，WebProvider 做 normalize + 截断。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Union


class WebSearchBackend(Protocol):
    """Backend 协议：backend_id + search(...) -> list of dict 或 normalized_response { items, summary?, raw_provider_payload? }。"""

    @property
    def backend_id(self) -> str:
        """例如 ddg_html, searxng, bocha, stub。"""
        ...

    def search(
        self,
        query: str,
        max_results: int,
        timeout_ms: int,
        *,
        remaining_budget_ms: Optional[int] = None,
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """返回原始结果列表，或 normalized_response dict（含 items；可选 summary、raw_provider_payload）。
        remaining_budget_ms<=0 时 backend 可跳过（返回 [] 或 { items: [] }）。"""
        ...


class WebFetchBackend(Protocol):
    """Backend 协议：backend_id + fetch(url, timeout_ms, *, artifact_dir?) -> raw dict；WebProvider 做 normalize 到 canonical。"""

    @property
    def backend_id(self) -> str:
        """例如 stub, httpx。"""
        ...

    def fetch(
        self,
        url: str,
        timeout_ms: int,
        *,
        artifact_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """返回原始结果（含 url, status_code, content_type, text, truncated 等）；可选 artifact_dir 时落盘并返回 artifact_paths。"""
        ...
