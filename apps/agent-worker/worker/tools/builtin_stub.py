"""Stub implementations for web.search and web.fetch (no real network)."""

from __future__ import annotations

from typing import Any, Dict, List


def web_search_stub(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Stub: return fixed list of sources with provider=stub."""
    query = args.get("query", "")[:50]
    return [
        {
            "title": f"Stub result for: {query}",
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
    ]


def web_fetch_stub(args: Dict[str, Any]) -> Dict[str, Any]:
    """Stub: return fake content per url."""
    urls = args.get("urls") or []
    if not isinstance(urls, list):
        urls = []
    contents = {u: f"Stub content for {u}" for u in urls[:20]}
    return {"contents": contents}
