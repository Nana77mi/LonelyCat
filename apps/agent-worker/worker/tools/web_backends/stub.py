"""Stub WebSearchBackend：固定 2～3 条结果，不打网。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class StubWebSearchBackend:
    """Stub backend：search() 返回固定 2～3 条，便于测试。"""

    backend_id: str = "stub"

    def search(
        self,
        query: str,
        max_results: int,
        timeout_ms: int,
        *,
        remaining_budget_ms: Optional[int] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """返回 2～3 条确定性结果。"""
        q = (query or "")[:50]
        return [
            {
                "title": f"Stub result for: {q}",
                "url": "https://example.com/stub/1",
                "snippet": "Stub snippet 1.",
                "provider": "stub",
            },
            {
                "title": "Stub result 2",
                "url": "https://example.com/stub/2",
                "snippet": "Stub snippet 2.",
                "provider": "stub",
            },
            {
                "title": "Stub result 3",
                "url": "https://example.com/stub/3",
                "snippet": "Stub snippet 3.",
                "provider": "stub",
            },
        ][:max(1, min(max_results, 10))]
