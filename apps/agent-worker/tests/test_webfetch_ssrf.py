"""Tests for webfetch SSRF: block private/loopback/link-local IPv4 and IPv6."""

import socket
from unittest.mock import patch

import pytest

from worker.tools.web_backends.errors import WebSSRFBlockedError
from worker.tools.webfetch.ssrf import check_ssrf_blocked


def test_ssrf_blocks_127_0_0_1():
    """http://127.0.0.1 必须拒绝，error=ssrf_blocked。"""
    with pytest.raises(WebSSRFBlockedError) as exc_info:
        check_ssrf_blocked("https://127.0.0.1/path")
    assert exc_info.value.code == "ssrf_blocked"


def test_ssrf_blocks_localhost():
    """http://localhost 解析后为环回，必须拒绝。"""
    with patch("socket.gethostbyname_ex", return_value=(["localhost", "localhost.localdomain"], [], ["127.0.0.1"])):
        with pytest.raises(WebSSRFBlockedError):
            check_ssrf_blocked("https://localhost/page")


def test_ssrf_blocks_169_254_169_254():
    """169.254.169.254（常见元数据）必须拒绝。"""
    with pytest.raises(WebSSRFBlockedError):
        check_ssrf_blocked("https://169.254.169.254/latest/")


def test_ssrf_blocks_10_0_0_1():
    """10.0.0.1 私网必须拒绝。"""
    with pytest.raises(WebSSRFBlockedError):
        check_ssrf_blocked("https://10.0.0.1/")


def test_ssrf_blocks_192_168_1_1():
    """192.168.1.1 私网必须拒绝。"""
    with pytest.raises(WebSSRFBlockedError):
        check_ssrf_blocked("http://192.168.1.1/")


def test_ssrf_blocks_ipv6_loopback():
    """::1 必须拒绝。"""
    with pytest.raises(WebSSRFBlockedError):
        check_ssrf_blocked("https://[::1]/path")


def test_ssrf_blocks_ipv6_private():
    """fc00::/7 私有必须拒绝。"""
    with pytest.raises(WebSSRFBlockedError):
        check_ssrf_blocked("https://[fc00::1]/")


def test_ssrf_blocks_ipv6_link_local():
    """fe80::/10 链路本地必须拒绝。"""
    with pytest.raises(WebSSRFBlockedError):
        check_ssrf_blocked("https://[fe80::1]/")


def test_ssrf_allows_public_hostname():
    """example.com 解析为公网 IP 时允许（mock 解析）。"""
    with patch("socket.gethostbyname_ex", return_value=(["example.com"], [], ["93.184.216.34"])):
        check_ssrf_blocked("https://example.com/")  # no raise


def test_ssrf_dns_rebind_blocks_if_any_ip_private():
    """DNS rebind：hostname 解析出任一私网 IP 即拒绝。"""
    # 模拟解析返回 93.184.216.34 和 127.0.0.1
    with patch("socket.gethostbyname_ex", return_value=(["evil.com"], [], ["93.184.216.34", "127.0.0.1"])):
        with pytest.raises(WebSSRFBlockedError):
            check_ssrf_blocked("https://evil.com/")
