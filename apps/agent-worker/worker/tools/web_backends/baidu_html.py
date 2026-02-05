"""BaiduHtmlBackend: 百度 HTML 搜索后端，无 key；解析用 baidu_parser。仅负责 search，不解析 /link?url= 落地页。"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Union
from urllib.parse import quote

import httpx

from worker.tools.web_backends.baidu_parser import (
    detect_no_results,
    detect_possible_results_structure,
    get_serp_probe,
    parse_baidu_html,
)
from worker.tools.web_backends.errors import (
    WebBlockedError,
    WebNetworkError,
    WebParseError,
    WebTimeoutError,
)

BAIDU_SEARCH_URL = "https://www.baidu.com/s"
BAIDU_HOME = "https://www.baidu.com/"
# 固定桌面 Chrome UA，避免百度按 UA 返回简版/移动版导致 DOM 与 parser 不匹配
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_baidu_cooldown: Dict[str, float] = {}


def _normalize_proxy_for_key(proxy: Optional[Union[str, Dict[str, Any]]]) -> str:
    """归一化为稳定字符串；dict 用 json.dumps(sort_keys)；URL 中含认证时脱敏，避免 key 泄露 user:pass。"""
    if proxy is None:
        return ""
    if isinstance(proxy, dict):
        return json.dumps(proxy, sort_keys=True)[:512]
    p = str(proxy).strip()[:512]
    # 脱敏：://user:password@ -> ://***@，同一 proxy 主机同 key，不写凭据
    if "@" in p and "://" in p:
        p = re.sub(r"://[^:]+:[^@]+@", "://***@", p)
    return p


def _cooldown_key(proxy: Optional[Union[str, Dict[str, Any]]], user_agent: str) -> str:
    """Cooldown key：proxy_enabled + proxy 归一化（脱敏）+ UA 哈希前缀。同一配置多次运行一致；切换 proxy/UA 必换 key。"""
    p = _normalize_proxy_for_key(proxy)
    ua_raw = (user_agent or "").strip()
    ua_prefix = hashlib.sha256(ua_raw.encode("utf-8", errors="replace")).hexdigest()[:8] if ua_raw else ""
    return f"{bool(p)}:{p}:{ua_prefix}"


class BaiduHtmlSearchBackend:
    """百度 HTML 后端：GET www.baidu.com/s?wd=，解析结果；无 key。复用 web.fetch 的 timeout/proxy/user_agent。"""

    backend_id: str = "baidu_html"

    def __init__(
        self,
        timeout_ms: int = 15000,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
        *,
        cooldown_minutes: int = 10,
        warm_up_enabled: bool = True,
        warm_up_ttl_seconds: int = 600,
        client_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._timeout_ms = max(1000, timeout_ms)
        self._proxy = (proxy or "").strip() or None
        self._user_agent = (user_agent or USER_AGENT).strip() or USER_AGENT
        self._cooldown_minutes = max(0, cooldown_minutes)
        self._warm_up_enabled = bool(warm_up_enabled)
        self._warm_up_ttl_seconds = max(0, warm_up_ttl_seconds)
        self._client_factory = client_factory
        self._client: Optional[httpx.Client] = None
        self._last_warm_up_time: float = 0.0

    def _get_client(self, timeout_sec: float) -> Any:
        """获取或创建 httpx.Client（实例级复用）。"""
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                self._client = httpx.Client(
                    timeout=timeout_sec,
                    proxy=self._proxy,
                )
        return self._client

    def close(self) -> None:
        """关闭持有的 client，下次 search 会重新创建。"""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def search(self, query: str, max_results: int, timeout_ms: int) -> List[Dict[str, Any]]:
        """请求百度 HTML 并解析；仅 captcha_required 设 cooldown（按 key）；403/429 不设。"""
        timeout_sec = max(1.0, timeout_ms / 1000.0)
        key = _cooldown_key(self._proxy, self._user_agent)
        now = time.time()
        until = _baidu_cooldown.get(key, 0.0)
        if until > now and self._cooldown_minutes > 0:
            remaining = max(0, int(round(until - now)))
            meta = {
                "query": query,
                "backend": self.backend_id,
                "cooldown_until": until,
                "cooldown_remaining_sec": remaining,
            }
            mins = max(1, (remaining + 59) // 60)
            raise WebBlockedError(
                f"百度验证码冷却中，约 {mins} 分钟后可重试或切换 DuckDuckGo",
                detail_code="captcha_cooldown",
                serp_meta=meta,
            )

        headers = {"User-Agent": self._user_agent}
        try:
            client = self._get_client(timeout_sec)
        except httpx.TimeoutException as e:
            raise WebTimeoutError(str(e)[:500]) from e
        except httpx.RequestError as e:
            raise WebNetworkError(str(e)[:500]) from e

        # Warm-up：TTL 内只做一次；follow_redirects=False，若 302→wappass 则直接 captcha_required
        did_warm = False
        if self._warm_up_enabled and self._warm_up_ttl_seconds > 0:
            do_warm = self._last_warm_up_time == 0 or (now - self._last_warm_up_time) > self._warm_up_ttl_seconds
            if do_warm:
                try:
                    resp_warm = client.get(BAIDU_HOME, headers=headers, follow_redirects=False)
                except httpx.TimeoutException as e:
                    raise WebTimeoutError(str(e)[:500]) from e
                except httpx.RequestError as e:
                    raise WebNetworkError(str(e)[:500]) from e
                raw_warm = resp_warm.text
                loc_warm = (resp_warm.headers.get("location") or "").strip()
                href_warm = ""
                if not loc_warm:
                    m = re.search(r'<a\s+[^>]*href=["\']([^"\']+)["\']', raw_warm, re.I | re.S)
                    href_warm = (m.group(1).strip() if m else "")[:2048]
                loc_lower = (loc_warm or href_warm).lower()
                if "wappass" in loc_lower or "captcha" in loc_lower or ("wappass.baidu.com" in raw_warm):
                    if self._cooldown_minutes > 0:
                        _baidu_cooldown[key] = time.time() + self._cooldown_minutes * 60
                    meta_warm = {
                        "query": query,
                        "backend": self.backend_id,
                        "warm_up_attempted": True,
                        "warm_up_used": True,
                        "warm_up_result": "captcha_redirect",
                        "warm_up_last_at": None,
                        "status_code": resp_warm.status_code,
                    }
                    raise WebBlockedError(
                        "百度首页即重定向到验证页",
                        detail_code="captcha_required",
                        serp_html=raw_warm,
                        serp_meta=meta_warm,
                    )
                self._last_warm_up_time = time.time()
                did_warm = True

        url = BAIDU_SEARCH_URL + "?wd=" + quote(query.strip()) + "&rn=" + str(max(1, min(max_results, 10)))
        try:
            resp = client.get(url, headers=headers, follow_redirects=False)
        except httpx.TimeoutException as e:
            raise WebTimeoutError(str(e)[:500]) from e
        except httpx.RequestError as e:
            raise WebNetworkError(str(e)[:500]) from e

        if resp.status_code == 403:
            raise WebBlockedError(f"HTTP 403", detail_code="http_403")
        if resp.status_code == 429:
            raise WebBlockedError(f"HTTP 429", detail_code="http_429")

        raw_html = resp.text

        def _first_href_from_body(html: str) -> str:
            """从 body 抽取第一个 <a href="..."> 的 href，用于 302 时 Location 缺失的 fallback。"""
            m = re.search(r'<a\s+[^>]*href=["\']([^"\']+)["\']', html, re.I | re.S)
            return (m.group(1).strip() if m else "")[:2048]

        def _serp_meta(
            reason: str,
            redirect_location: Optional[str] = None,
            warm_up_used: Optional[bool] = None,
            warm_up_last_at: Optional[float] = None,
        ) -> Dict[str, Any]:
            """构建 serp_meta；不写 cookie/完整请求头/proxy URL 凭据，仅 proxy_enabled；redirect_location 截断 2048。"""
            try:
                content_len = len(resp.content) if hasattr(resp, "content") and resp.content is not None else len(raw_html)
            except Exception:
                content_len = len(raw_html)
            meta: Dict[str, Any] = {
                "query": query,
                "backend": self.backend_id,
                "status_code": resp.status_code,
                "content_type": (resp.headers.get("content-type") or "")[:200],
                "bytes_read": content_len,
                "final_url": str(getattr(resp, "url", "") or ""),
                "user_agent": self._user_agent[:200],
                "proxy_enabled": bool(self._proxy),
                "probe": get_serp_probe(raw_html),
                "reason": reason,
            }
            if redirect_location is not None:
                meta["redirect_location"] = redirect_location[:2048]
            if warm_up_used is not None:
                meta["warm_up_used"] = warm_up_used
            if warm_up_last_at is not None:
                meta["warm_up_last_at"] = warm_up_last_at
            return meta

        # 302 重定向：优先看 Location，缺失时从 body <a href="..."> 抽取；命中 wappass/captcha → captcha_required
        if resp.status_code == 302:
            location = (resp.headers.get("location") or "").strip()
            href_from_body = _first_href_from_body(raw_html) if not location else ""
            redirect_location = location or href_from_body

            def _is_captcha_redirect(loc_or_href: str) -> bool:
                if not loc_or_href:
                    return False
                loc_lower = loc_or_href.lower()
                return "wappass" in loc_lower or "wappass.baidu.com" in loc_lower or "captcha" in loc_lower

            if _is_captcha_redirect(location):
                if self._cooldown_minutes > 0:
                    _baidu_cooldown[key] = time.time() + self._cooldown_minutes * 60
                raise WebBlockedError(
                    "百度重定向到验证页（Location）",
                    detail_code="captcha_required",
                    serp_html=raw_html,
                    serp_meta=_serp_meta(
                        "captcha_redirect",
                        redirect_location=location or None,
                        warm_up_used=did_warm,
                        warm_up_last_at=self._last_warm_up_time if did_warm else None,
                    ),
                )
            if _is_captcha_redirect(href_from_body):
                if self._cooldown_minutes > 0:
                    _baidu_cooldown[key] = time.time() + self._cooldown_minutes * 60
                raise WebBlockedError(
                    "百度返回验证/安全页（body 内链接指向验证码）",
                    detail_code="captcha_required",
                    serp_html=raw_html,
                    serp_meta=_serp_meta(
                        "captcha_redirect",
                        redirect_location=href_from_body or None,
                        warm_up_used=did_warm,
                        warm_up_last_at=self._last_warm_up_time if did_warm else None,
                    ),
                )
            if "wappass.baidu.com" in raw_html or ("captcha" in raw_html.lower() and "baidu.com" in raw_html):
                if self._cooldown_minutes > 0:
                    _baidu_cooldown[key] = time.time() + self._cooldown_minutes * 60
                raise WebBlockedError(
                    "百度返回验证/安全页（正文含验证链接）",
                    detail_code="captcha_required",
                    serp_html=raw_html,
                    serp_meta=_serp_meta(
                "captcha_redirect",
                redirect_location=redirect_location or None,
                warm_up_used=did_warm,
                warm_up_last_at=self._last_warm_up_time if did_warm else None,
            ),
                )

        items, err = parse_baidu_html(raw_html)

        if err == "captcha_required":
            if self._cooldown_minutes > 0:
                _baidu_cooldown[key] = time.time() + self._cooldown_minutes * 60
            raise WebBlockedError(
                "Page indicates captcha or security check",
                detail_code="captcha_required",
                serp_html=raw_html,
                serp_meta=_serp_meta(
                "captcha_required",
                warm_up_used=did_warm,
                warm_up_last_at=self._last_warm_up_time if did_warm else None,
            ),
            )
        if err == "parse_failed":
            raise WebParseError(
                "百度页面解析失败（输入异常或解析器异常），可尝试配置 proxy 或更换网络后再试",
                serp_html=raw_html,
                serp_meta=_serp_meta(
                "parse_failed",
                warm_up_used=did_warm,
                warm_up_last_at=self._last_warm_up_time if did_warm else None,
            ),
            )
        if items:
            return items[: max(1, min(max_results, 10))]
        # items == [] 且 err is None：区分「真实无结果」与「DOM 不匹配」
        if detect_no_results(raw_html):
            return []
        if detect_possible_results_structure(raw_html):
            raise WebParseError(
                "百度结果页 DOM 与解析器不匹配（可能 SERP 改版或 UA 导致 layout 不同），建议使用桌面 Chrome UA 或检查 selector",
                serp_html=raw_html,
                serp_meta=_serp_meta(
                "dom_mismatch",
                warm_up_used=did_warm,
                warm_up_last_at=self._last_warm_up_time if did_warm else None,
            ),
            )
        raise WebParseError(
            "百度结果页结构无法识别，既非无结果页也非已知 SERP 结构；已写入 search/serp.html 与 search/serp.meta.json 便于排查",
            serp_html=raw_html,
            serp_meta=_serp_meta(
            "unknown_structure",
            warm_up_used=did_warm,
            warm_up_last_at=self._last_warm_up_time if did_warm else None,
        ),
        )
