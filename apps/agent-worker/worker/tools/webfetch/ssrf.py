"""SSRF 防护：解析 host 到所有 IP，任一为私网/环回/链路本地即拒绝。"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from worker.tools.web_backends.errors import WebSSRFBlockedError


def _is_blocked_ip(ip_str: str) -> bool:
    """判断单个 IP（字符串）是否为私网/环回/链路本地。"""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # 无法解析视为不安全
    if ip.is_loopback:
        return True
    if ip.is_private:  # 10/8, 172.16/12, 192.168/16
        return True
    if ip.is_link_local:  # 169.254/16, fe80::/10
        return True
    # IPv6 唯一本地 fc00::/7
    if getattr(ip, "is_private", None) and ip.is_private:
        return True
    if ip.version == 6:
        try:
            if ip in ipaddress.IPv6Network("fc00::/7"):
                return True
        except Exception:
            pass
    return False


def _host_from_url(url: str) -> str:
    """从 URL 取出 host（含 [::1] 形式）。"""
    parsed = urlparse(url)
    netloc = parsed.netloc or ""
    if not netloc:
        return ""
    # 去掉 port
    if "]" in netloc:
        # IPv6 [::1]:443
        end = netloc.rfind("]")
        return netloc[: end + 1]
    if ":" in netloc and "[" not in netloc:
        return netloc.split(":")[0]
    return netloc


def _resolve_host_to_ips(host: str) -> list[str]:
    """解析 hostname 到 IP 列表；若已是 IP 则返回 [ip]。"""
    host_clean = host.strip("[]")
    # 先尝试当作 IP
    try:
        ipaddress.ip_address(host_clean)
        return [host_clean]
    except ValueError:
        pass
    try:
        # gethostbyname_ex 返回 (hostname, aliaslist, ipaddrlist)
        _, _, ipaddrlist = socket.gethostbyname_ex(host_clean)
        return list(ipaddrlist) if ipaddrlist else []
    except socket.gaierror:
        return []
    except Exception:
        return []


def check_ssrf_blocked(url: str) -> None:
    """若 URL 的 host 解析到任一首选 IP 为私网/环回/链路本地则抛 WebSSRFBlockedError。"""
    if not url or not isinstance(url, str):
        return
    host = _host_from_url(url.strip())
    if not host:
        return
    host_clean = host.strip("[]")
    ips = _resolve_host_to_ips(host_clean)
    for ip_str in ips:
        if _is_blocked_ip(ip_str):
            raise WebSSRFBlockedError(f"SSRF blocked: {host} resolves to private/loopback/link-local {ip_str}")
