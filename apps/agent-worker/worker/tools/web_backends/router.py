"""WebSearchRouter: 包装多个 WebSearchBackend，按顺序尝试（后续可加 fallback）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from worker.tools.web_backends.base import WebSearchBackend


class WebSearchRouter:
    """Router：持有一组 providers，search() 委托给第一个（后续可扩展 fallback）。"""

    def __init__(self, providers: List[WebSearchBackend]) -> None:
        self._providers = list(providers) if providers else []

    @property
    def backend_id(self) -> str:
        """与第一个 provider 一致；无 provider 时为 stub。"""
        if self._providers:
            return self._providers[0].backend_id
        return "stub"

    def search(
        self,
        query: str,
        max_results: int,
        timeout_ms: int,
        *,
        remaining_budget_ms: Optional[int] = None,
        **kwargs: Any,
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """委托给第一个 provider；后续可在此做 fallback（失败时尝试下一个）。"""
        if not self._providers:
            return []
        return self._providers[0].search(
            query,
            max_results,
            timeout_ms,
            remaining_budget_ms=remaining_budget_ms,
            **kwargs,
        )
