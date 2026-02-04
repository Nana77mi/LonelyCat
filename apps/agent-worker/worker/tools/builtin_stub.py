"""Stub implementations for web.search and web.fetch (no real network)."""

from __future__ import annotations

from typing import Any, Dict, List


def web_search_stub(args: Dict[str, Any]) -> Dict[str, Any]:
    """Stub: return canonical shape {"items": [...]} with provider=stub（与 WebProvider 一致，list 已淘汰）。"""
    query = (args.get("query") or "")[:50] if isinstance(args.get("query"), str) else ""
    items: List[Dict[str, Any]] = [
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
    return {"items": items}


def web_fetch_stub(args: Dict[str, Any]) -> Dict[str, Any]:
    """Stub: return canonical fetch shape for single url（与 web.fetch 合同一致）。"""
    url = args.get("url")
    if not url and args.get("urls"):
        urls = args.get("urls")
        if isinstance(urls, list) and urls:
            url = urls[0]
    if not url or not isinstance(url, str):
        url = "https://example.com/stub"
    url = url.strip()
    return {
        "url": url,
        "status_code": 200,
        "content_type": "text/html",
        "text": f"Stub content for {url}",
        "truncated": False,
    }
