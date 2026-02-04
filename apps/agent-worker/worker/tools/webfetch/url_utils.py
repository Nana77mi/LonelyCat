"""URL 规范化：去 fragment、去跟踪参数。"""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# 要移除的 query 参数名（小写）；utm_* 用前缀匹配
TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAM_NAMES = frozenset(("spm", "fbclid"))


def normalize_fetch_url(url: str) -> str:
    """规范化 URL：去掉 #fragment；query 中移除 utm_*, spm, fbclid。"""
    if not url or not isinstance(url, str):
        return url.strip() if url else ""
    u = url.strip()
    parsed = urlparse(u)
    if not parsed.scheme or not parsed.netloc:
        return u
    # 去掉 fragment
    frag = ""
    # 过滤 query
    query_dict = parse_qs(parsed.query, keep_blank_values=True)
    filtered = {}
    for k, v in query_dict.items():
        key_lower = k.lower()
        if key_lower in TRACKING_PARAM_NAMES:
            continue
        if any(key_lower.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES):
            continue
        filtered[k] = v
    new_query = urlencode(filtered, doseq=True)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        frag,
    ))
