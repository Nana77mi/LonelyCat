"""BaiduHtmlSearchBackend tests: mock HTTP, no network. 403/429 用 status_code 判定。"""

import os
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from worker.tools.web_backends.baidu_html import (
    BaiduHtmlSearchBackend,
    _baidu_cooldown,
    _cooldown_key,
    _normalize_proxy_for_key,
)
from worker.tools.web_backends.errors import (
    WebBlockedError,
    WebNetworkError,
    WebParseError,
    WebTimeoutError,
)

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures", "baidu_html")


@pytest.fixture(autouse=True)
def _clear_baidu_cooldown():
    """每个测试前后清空模块级 cooldown，避免测试间污染。"""
    _baidu_cooldown.clear()
    yield
    _baidu_cooldown.clear()


def _load_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_cooldown_key_same_config_stable():
    """同一 proxy+UA 多次调用 key 一致。"""
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
    k1 = _cooldown_key(None, ua)
    k2 = _cooldown_key(None, ua)
    assert k1 == k2
    k3 = _cooldown_key("http://127.0.0.1:8080", ua)
    k4 = _cooldown_key("http://127.0.0.1:8080", ua)
    assert k3 == k4


def test_cooldown_key_different_proxy_different_key():
    """切换 proxy 必换 key。"""
    ua = "Chrome/120"
    k_none = _cooldown_key(None, ua)
    k_proxy = _cooldown_key("http://127.0.0.1:8080", ua)
    assert k_none != k_proxy


def test_cooldown_key_proxy_with_credentials_not_in_key():
    """proxy URL 含 user:pass 时 key 中不包含明文密码。"""
    ua = "Chrome/120"
    key = _cooldown_key("http://user:secret@proxy.example.com:8080", ua)
    assert "secret" not in key
    assert "user" not in key or "***" in key
    # 同一主机不同凭据应得到同一 key（按主机隔离 cooldown）
    key2 = _cooldown_key("http://other:pass@proxy.example.com:8080", ua)
    assert key == key2


def test_normalize_proxy_dict_stable():
    """dict proxy 归一化为稳定 json 字符串。"""
    p = _normalize_proxy_for_key({"https": "http://proxy:8080", "http": "http://proxy:8080"})
    assert "proxy" in p
    p2 = _normalize_proxy_for_key({"http": "http://proxy:8080", "https": "http://proxy:8080"})
    assert p == p2


def test_baidu_backend_default_ua_is_desktop_chrome_not_lonelycat():
    """backend 使用 user_agent=None 时，实际 UA 为桌面 Chrome，且不含 LonelyCat。"""
    backend = BaiduHtmlSearchBackend(timeout_ms=5000, user_agent=None)
    ua = backend._user_agent
    assert "Chrome/" in ua, "default UA must be desktop Chrome"
    assert "LonelyCat" not in ua, "default UA must not be LonelyCat/1.0"


def test_baidu_backend_search_returns_items_and_respects_max_results():
    """Mock 200 + results_basic.html；max_results=2 → 返回 2 条，含 title/url/snippet。"""
    html = _load_fixture("results_basic.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend(timeout_ms=5000)
        items = backend.search("test", max_results=2, timeout_ms=5000)
    assert len(items) == 2
    for it in items:
        assert "title" in it and "url" in it and "snippet" in it
    assert items[0]["title"] == "First Result Title"
    assert "example.com" in items[0]["url"]


def test_baidu_backend_http_403_raises_web_blocked_detail_code_http_403():
    """Mock status_code=403 → WebBlockedError，detail_code=http_403。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = ""
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        with pytest.raises(WebBlockedError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebBlocked"
    assert getattr(exc_info.value, "detail_code", None) == "http_403"


def test_baidu_backend_http_429_raises_web_blocked_detail_code_http_429():
    """Mock status_code=429 → WebBlockedError，detail_code=http_429。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = ""
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        with pytest.raises(WebBlockedError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebBlocked"
    assert getattr(exc_info.value, "detail_code", None) == "http_429"


def test_baidu_backend_captcha_html_raises_web_blocked_detail_code_captcha_required():
    """Mock 200 + blocked_captcha.html（验证码关键词）→ WebBlockedError，detail_code=captcha_required。"""
    html = _load_fixture("blocked_captcha.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        with pytest.raises(WebBlockedError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebBlocked"
    assert getattr(exc_info.value, "detail_code", None) == "captcha_required"


def test_baidu_backend_timeout_raises_timeout():
    """Mock TimeoutException → WebTimeoutError。"""
    mock_client = MagicMock()
    mock_client.get.side_effect = httpx.TimeoutException("timed out")
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        with pytest.raises(WebTimeoutError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "Timeout"


def test_baidu_backend_request_error_raises_network_error():
    """Mock RequestError → WebNetworkError。"""
    mock_client = MagicMock()
    mock_client.get.side_effect = httpx.RequestError("connection failed")
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        with pytest.raises(WebNetworkError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "NetworkError"


def test_baidu_backend_no_results_html_returns_empty_list():
    """Mock 200 + no_results.html（没有找到相关结果）→ 返回 []，不抛错（真实无结果）。"""
    html = _load_fixture("no_results.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        items = backend.search("asdasdzzzzxxx", max_results=5, timeout_ms=5000)
    assert items == []


def test_baidu_backend_zero_items_unknown_structure_raises_web_parse_error():
    """Mock 200 + empty_and_malformed.html（无 SERP 标记、0 条）→ WebParseError（unknown structure），且带 serp_html/serp_meta。"""
    html = _load_fixture("empty_and_malformed.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp.content = html.encode("utf-8")
    mock_resp.url = "https://www.baidu.com/s?wd=x"
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        with pytest.raises(WebParseError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebParseError"
    assert getattr(exc_info.value, "serp_html", None) == html
    meta = getattr(exc_info.value, "serp_meta", None)
    assert meta is not None
    assert meta.get("reason") == "unknown_structure"
    assert meta.get("backend") == "baidu_html"
    assert "probe" in meta
    assert "title" in meta["probe"] and "has_c_container" in meta["probe"]


def test_baidu_backend_zero_items_dom_mismatch_raises_web_parse_error():
    """Mock 200 + 页面有 SERP 结构但 parser 返回 0 条（DOM 不匹配）→ WebParseError。"""
    html = _load_fixture("results_basic.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    def _parse_return_empty(_html):
        return [], None

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client), patch(
        "worker.tools.web_backends.baidu_html.parse_baidu_html", side_effect=_parse_return_empty
    ):
        backend = BaiduHtmlSearchBackend()
        with pytest.raises(WebParseError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebParseError"
    assert "DOM" in str(exc_info.value) or "不匹配" in str(exc_info.value)


def test_baidu_backend_empty_response_parse_failed_raises_web_parse_error():
    """Mock 200 + 空 body（parse_failed）→ WebParseError。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ""
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        with pytest.raises(WebParseError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebParseError"


def test_baidu_backend_302_captcha_serp_meta_user_agent_is_chrome_not_lonelycat():
    """302 + body 含 wappass 链接时 WebBlockedError.serp_meta.user_agent 为桌面 Chrome，不含 LonelyCat。"""
    html = '<a href="https://wappass.baidu.com/static/captcha/tuxing_v2.html">Found</a>.'
    mock_resp = MagicMock()
    mock_resp.status_code = 302
    mock_resp.text = html
    mock_resp.headers = {}
    mock_resp.content = html.encode("utf-8")
    mock_resp.url = "https://www.baidu.com/s?wd=x"
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend(
            timeout_ms=5000,
            user_agent=None,
            warm_up_enabled=False,
        )
        with pytest.raises(WebBlockedError) as exc_info:
            backend.search("x", max_results=5, timeout_ms=5000)
    assert exc_info.value.code == "WebBlocked"
    assert getattr(exc_info.value, "detail_code", None) == "captcha_required"
    meta = getattr(exc_info.value, "serp_meta", None)
    assert meta is not None
    ua = meta.get("user_agent", "")
    assert "Chrome/" in ua, "serp_meta.user_agent must be desktop Chrome"
    assert "LonelyCat" not in ua, "serp_meta.user_agent must not be LonelyCat/1.0"
    assert meta.get("redirect_location") is not None, "302 captcha must set redirect_location"


def test_baidu_backend_query_encoded_in_url():
    """search 调用时 URL 含编码后的 query。"""
    html = _load_fixture("results_basic.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("worker.tools.web_backends.baidu_html.httpx.Client", return_value=mock_client):
        backend = BaiduHtmlSearchBackend()
        backend.search("hello world", max_results=5, timeout_ms=5000)
    call_args = mock_client.get.call_args
    assert call_args is not None
    url = call_args[0][0] if call_args[0] else call_args[1].get("url")
    assert url is not None
    assert "wd=" in url
    assert "hello" in url or "hello%20world" in url or "hello+world" in url


# ---- TDD: cooldown 闭环（触发 captcha → 设 cooldown → TTL 内直接 captcha_cooldown 不发请求；过期/换 key 可再试）----


def test_baidu_backend_captcha_sets_cooldown_and_next_call_raises_captcha_cooldown_without_http():
    """第一次 search：302 captcha → 抛 captcha_required 并设置 cooldown；第二次 search（不推进时间）→ 直接 captcha_cooldown，0 次 HTTP。"""
    html = '<a href="https://wappass.baidu.com/static/captcha/tuxing_v2.html">Found</a>.'
    mock_resp = MagicMock()
    mock_resp.status_code = 302
    mock_resp.text = html
    mock_resp.headers = {}
    mock_resp.content = html.encode("utf-8")
    mock_resp.url = "https://www.baidu.com/s?wd=x"
    get_calls = []

    def track_get(*args, **kwargs):
        get_calls.append(1)
        return mock_resp

    mock_client = MagicMock()
    mock_client.get.side_effect = track_get
    backend = BaiduHtmlSearchBackend(
        timeout_ms=5000,
        user_agent=None,
        proxy=None,
        cooldown_minutes=10,
        warm_up_enabled=False,
        client_factory=lambda: mock_client,
    )
    with pytest.raises(WebBlockedError) as exc_info:
        backend.search("x", max_results=5, timeout_ms=5000)
    assert getattr(exc_info.value, "detail_code", None) == "captcha_required"
    assert len(get_calls) == 1
    get_calls.clear()
    with pytest.raises(WebBlockedError) as exc_info2:
        backend.search("y", max_results=5, timeout_ms=5000)
    assert getattr(exc_info2.value, "detail_code", None) == "captcha_cooldown"
    assert len(get_calls) == 0, "cooldown 期间不应发起 HTTP"


def test_baidu_backend_cooldown_expires_then_allows_request():
    """mock 时间超过 cooldown_until 后，再次 search 应允许发请求并成功。"""
    from worker.tools.web_backends.baidu_html import _cooldown_key

    html = _load_fixture("results_basic.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    backend = BaiduHtmlSearchBackend(
        timeout_ms=5000,
        proxy=None,
        warm_up_enabled=False,
        client_factory=lambda: mock_client,
    )
    key = _cooldown_key(backend._proxy, backend._user_agent)
    _baidu_cooldown[key] = time.time() - 120  # 2 分钟前过期
    items = backend.search("x", max_results=5, timeout_ms=5000)
    assert len(items) >= 1
    assert mock_client.get.called


def test_baidu_backend_cooldown_keyed_by_proxy_or_ua():
    """无代理触发 cooldown 后，启用代理（或换 UA）可重新请求，不被误伤。key = (proxy_enabled, proxy, ua)。"""
    html_captcha = '<a href="https://wappass.baidu.com/static/captcha/tuxing_v2.html">Found</a>.'
    html_ok = _load_fixture("results_basic.html")
    mock_resp_captcha = MagicMock()
    mock_resp_captcha.status_code = 302
    mock_resp_captcha.text = html_captcha
    mock_resp_captcha.headers = {}
    mock_resp_captcha.content = html_captcha.encode("utf-8")
    mock_resp_captcha.url = "https://www.baidu.com/s?wd=x"
    mock_resp_ok = MagicMock()
    mock_resp_ok.status_code = 200
    mock_resp_ok.text = html_ok
    mock_resp_ok.headers = {}
    mock_resp_ok.content = html_ok.encode("utf-8")
    mock_resp_ok.url = "https://www.baidu.com/s?wd=x"

    backend_no_proxy = BaiduHtmlSearchBackend(
        timeout_ms=5000,
        proxy=None,
        cooldown_minutes=10,
        warm_up_enabled=False,
        client_factory=lambda: MagicMock(get=MagicMock(return_value=mock_resp_captcha)),
    )
    with pytest.raises(WebBlockedError):
        backend_no_proxy.search("x", max_results=5, timeout_ms=5000)
    mock_with_proxy = MagicMock()
    mock_with_proxy.get.return_value = mock_resp_ok
    backend_with_proxy = BaiduHtmlSearchBackend(
        timeout_ms=5000,
        proxy="http://127.0.0.1:8080",
        cooldown_minutes=10,
        client_factory=lambda: mock_with_proxy,
    )
    items = backend_with_proxy.search("x", max_results=5, timeout_ms=5000)
    assert len(items) >= 1
    assert mock_with_proxy.get.called


# ---- cooldown keyed by proxy+UA, client_factory + close ----


def test_baidu_backend_cooldown_keyed_after_captcha_same_key_raises_captcha_cooldown_no_http():
    """同一 key（无代理）触发 captcha_required 后，再次 search 应直接 captcha_cooldown，不发起 HTTP。"""
    _baidu_cooldown.clear()
    html = '<a href="https://wappass.baidu.com/static/captcha/tuxing_v2.html">Found</a>.'
    mock_resp = MagicMock()
    mock_resp.status_code = 302
    mock_resp.text = html
    mock_resp.headers = {}
    mock_resp.content = html.encode("utf-8")
    mock_resp.url = "https://www.baidu.com/s?wd=x"
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    get_calls = []

    def track_get(*args, **kwargs):
        get_calls.append(1)
        return mock_resp

    mock_client.get.side_effect = track_get
    factory_calls = []

    def make_client():
        factory_calls.append(1)
        return mock_client

    backend = BaiduHtmlSearchBackend(
        timeout_ms=5000,
        user_agent=None,
        proxy=None,
        cooldown_minutes=10,
        warm_up_enabled=False,
        client_factory=make_client,
    )
    with pytest.raises(WebBlockedError) as exc_info:
        backend.search("x", max_results=5, timeout_ms=5000)
    assert getattr(exc_info.value, "detail_code", None) == "captcha_required"
    assert len(get_calls) == 1
    get_calls.clear()
    with pytest.raises(WebBlockedError) as exc_info2:
        backend.search("y", max_results=5, timeout_ms=5000)
    assert getattr(exc_info2.value, "detail_code", None) == "captcha_cooldown"
    assert len(get_calls) == 0, "cooldown 期间不应发起 HTTP"


def test_baidu_backend_cooldown_different_key_after_captcha_allows_http():
    """无代理触发 cooldown 后，换 proxy（新 key）应可立刻发请求。"""
    _baidu_cooldown.clear()
    html_captcha = '<a href="https://wappass.baidu.com/static/captcha/tuxing_v2.html">Found</a>.'
    html_ok = _load_fixture("results_basic.html")
    mock_resp_captcha = MagicMock()
    mock_resp_captcha.status_code = 302
    mock_resp_captcha.text = html_captcha
    mock_resp_captcha.headers = {}
    mock_resp_captcha.content = html_captcha.encode("utf-8")
    mock_resp_captcha.url = "https://www.baidu.com/s?wd=x"
    mock_resp_ok = MagicMock()
    mock_resp_ok.status_code = 200
    mock_resp_ok.text = html_ok
    mock_resp_ok.headers = {}
    mock_resp_ok.content = html_ok.encode("utf-8")
    mock_resp_ok.url = "https://www.baidu.com/s?wd=x"

    backend_no_proxy = BaiduHtmlSearchBackend(
        timeout_ms=5000,
        proxy=None,
        cooldown_minutes=10,
        warm_up_enabled=False,
        client_factory=lambda: MagicMock(get=MagicMock(return_value=mock_resp_captcha)),
    )
    with pytest.raises(WebBlockedError):
        backend_no_proxy.search("x", max_results=5, timeout_ms=5000)
    mock_with_proxy = MagicMock()
    mock_with_proxy.get.return_value = mock_resp_ok
    backend_with_proxy = BaiduHtmlSearchBackend(
        timeout_ms=5000,
        proxy="http://127.0.0.1:8080",
        cooldown_minutes=10,
        client_factory=lambda: mock_with_proxy,
    )
    items = backend_with_proxy.search("x", max_results=5, timeout_ms=5000)
    assert len(items) >= 1
    assert mock_with_proxy.get.called


def test_baidu_backend_429_does_not_set_cooldown_next_search_still_sends_http():
    """429 不写入 cooldown；同一 backend 下一次 search 仍会发 HTTP。"""
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.text = ""
    mock_resp_ok = MagicMock()
    mock_resp_ok.status_code = 200
    mock_resp_ok.text = _load_fixture("results_basic.html")
    mock_resp_ok.headers = {}
    mock_resp_ok.content = b""
    mock_resp_ok.url = "https://www.baidu.com/s?wd=x"
    get_calls = []

    def side_effect(*args, **kwargs):
        get_calls.append(1)
        if len(get_calls) == 1:
            return mock_resp_429
        return mock_resp_ok

    mock_client = MagicMock()
    mock_client.get.side_effect = side_effect
    backend = BaiduHtmlSearchBackend(
        timeout_ms=5000,
        cooldown_minutes=10,
        warm_up_enabled=False,
        client_factory=lambda: mock_client,
    )
    with pytest.raises(WebBlockedError) as exc_info:
        backend.search("x", max_results=5, timeout_ms=5000)
    assert getattr(exc_info.value, "detail_code", None) == "http_429"
    items = backend.search("x", max_results=5, timeout_ms=5000)
    assert len(items) >= 1
    assert len(get_calls) == 2, "429 后应允许再次请求"


def test_baidu_backend_client_factory_used_and_close_clears_client():
    """client_factory 被使用；close() 后下次 search 会重新创建 client（factory 再被调用）。"""
    html = _load_fixture("results_basic.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    factory_invocations = []

    def make_client():
        factory_invocations.append(1)
        c = MagicMock()
        c.get.return_value = mock_resp
        return c

    backend = BaiduHtmlSearchBackend(
        timeout_ms=5000,
        client_factory=make_client,
    )
    backend.search("a", max_results=5, timeout_ms=5000)
    assert len(factory_invocations) == 1
    backend.search("b", max_results=5, timeout_ms=5000)
    assert len(factory_invocations) == 1, "同一实例应复用 client"
    backend.close()
    backend.search("c", max_results=5, timeout_ms=5000)
    assert len(factory_invocations) == 2, "close 后应重新创建 client"


def test_baidu_backend_captcha_cooldown_serp_meta_has_cooldown_remaining():
    """captcha_cooldown 时 serp_meta 含 cooldown_remaining_sec 或 cooldown_until。"""
    _baidu_cooldown.clear()
    html = '<a href="https://wappass.baidu.com/static/captcha/tuxing_v2.html">Found</a>.'
    mock_resp = MagicMock()
    mock_resp.status_code = 302
    mock_resp.text = html
    mock_resp.headers = {}
    mock_resp.content = html.encode("utf-8")
    mock_resp.url = "https://www.baidu.com/s?wd=x"
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    backend = BaiduHtmlSearchBackend(
        timeout_ms=5000,
        proxy=None,
        cooldown_minutes=10,
        warm_up_enabled=False,
        client_factory=lambda: mock_client,
    )
    with pytest.raises(WebBlockedError):
        backend.search("x", max_results=5, timeout_ms=5000)
    with pytest.raises(WebBlockedError) as exc_info:
        backend.search("y", max_results=5, timeout_ms=5000)
    assert getattr(exc_info.value, "detail_code", None) == "captcha_cooldown"
    meta = getattr(exc_info.value, "serp_meta", None)
    assert meta is not None
    assert "cooldown_remaining_sec" in meta or "cooldown_until" in meta


# ---- TDD: warm-up TTL + warm-up 302 识别 ----


def test_baidu_backend_warm_up_ttl_first_search_does_warmup_then_search_second_in_ttl_only_search():
    """warm_up_enabled 且 TTL 内：第一次 search 发 warm-up + search（2 次 get）；第二次只 search（1 次 get）。"""
    _baidu_cooldown.clear()
    html = _load_fixture("results_basic.html")
    mock_resp_ok = MagicMock()
    mock_resp_ok.status_code = 200
    mock_resp_ok.text = html
    mock_resp_ok.headers = {}
    mock_resp_ok.content = html.encode("utf-8")
    mock_resp_ok.url = "https://www.baidu.com/s?wd=x"
    get_urls = []

    def track_get(url, *args, **kwargs):
        get_urls.append(url)
        return mock_resp_ok

    mock_client = MagicMock()
    mock_client.get.side_effect = track_get
    backend = BaiduHtmlSearchBackend(
        timeout_ms=5000,
        warm_up_enabled=True,
        warm_up_ttl_seconds=600,
        client_factory=lambda: mock_client,
    )
    backend.search("x", max_results=5, timeout_ms=5000)
    assert len(get_urls) == 2, "first search: warm-up + search"
    assert "www.baidu.com" in get_urls[0] and "/s" not in get_urls[0]
    assert "/s" in get_urls[1]
    get_urls.clear()
    backend.search("y", max_results=5, timeout_ms=5000)
    assert len(get_urls) == 1, "second search in TTL: only search"
    assert "/s" in get_urls[0]


def test_baidu_backend_warm_up_disabled_only_one_request():
    """warm_up_enabled=False 时只发 1 次请求（search）。"""
    _baidu_cooldown.clear()
    html = _load_fixture("results_basic.html")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    backend = BaiduHtmlSearchBackend(
        timeout_ms=5000,
        warm_up_enabled=False,
        client_factory=lambda: mock_client,
    )
    backend.search("x", max_results=5, timeout_ms=5000)
    assert mock_client.get.call_count == 1


def test_baidu_backend_warm_up_302_captcha_raises_captcha_required_no_search_request():
    """warm-up 返回 302→wappass 时直接 captcha_required，不发 search 请求；serp_meta 含 warm_up_attempted。"""
    _baidu_cooldown.clear()
    html_302 = '<a href="https://wappass.baidu.com/static/captcha/tuxing_v2.html">Found</a>.'
    mock_resp_302 = MagicMock()
    mock_resp_302.status_code = 302
    mock_resp_302.text = html_302
    mock_resp_302.headers = {}
    mock_resp_302.content = html_302.encode("utf-8")
    mock_resp_302.url = "https://www.baidu.com/"
    get_calls = []

    def track_get(*args, **kwargs):
        get_calls.append(1)
        return mock_resp_302

    mock_client = MagicMock()
    mock_client.get.side_effect = track_get
    backend = BaiduHtmlSearchBackend(
        timeout_ms=5000,
        warm_up_enabled=True,
        warm_up_ttl_seconds=600,
        client_factory=lambda: mock_client,
    )
    with pytest.raises(WebBlockedError) as exc_info:
        backend.search("x", max_results=5, timeout_ms=5000)
    assert getattr(exc_info.value, "detail_code", None) == "captcha_required"
    assert len(get_calls) == 1, "只发 warm-up，不发 search"
    meta = getattr(exc_info.value, "serp_meta", None)
    assert meta is not None
    assert meta.get("warm_up_attempted") is True
    assert meta.get("warm_up_result") == "captcha_redirect"
