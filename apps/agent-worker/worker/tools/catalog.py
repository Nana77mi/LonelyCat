"""ToolMeta v1 and ToolCatalog: multi-provider, capability_level, requires_confirm, timeout_ms (Phase 2.1/2.2 v0.1)."""

from __future__ import annotations

import atexit
import json
import logging
import os
import re
import shlex
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# MCP_SERVERS_JSON 中 server name 仅允许 [a-z0-9_]+，用于 tool 前缀与 provider_id
MCP_SERVER_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
MCP_SERVERS_JSON_RAW_TRUNCATE = 200

# 能力分级：L0 只读、L1 写文件、L2 执行/网络/CLI
CAPABILITY_L0 = "L0"
CAPABILITY_L1 = "L1"
CAPABILITY_L2 = "L2"


@dataclass
class ToolMeta:
    """Tool metadata: name, schema, side_effects, risk_level, capability_level, requires_confirm, timeout_ms."""

    name: str
    input_schema: Dict[str, Any]  # JSON Schema or minimal dict
    side_effects: bool = False
    risk_level: str = "read_only"  # read_only | write
    budget: Optional[Dict[str, Any]] = None
    provider_id: str = "builtin"
    # Phase 2.1
    capability_level: str = CAPABILITY_L0  # L0 | L1 | L2
    requires_confirm: bool = False
    timeout_ms: Optional[int] = None


def _builtin_tool_meta(provider_id: str = "builtin") -> List[ToolMeta]:
    return [
        ToolMeta(
            name="web.search",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            side_effects=False,
            risk_level="read_only",
            provider_id=provider_id,
            capability_level=CAPABILITY_L0,
            requires_confirm=False,
            timeout_ms=30_000,
        ),
        ToolMeta(
            name="web.fetch",
            input_schema={
                "type": "object",
                "properties": {"urls": {"type": "array", "items": {"type": "string"}}},
                "required": ["urls"],
            },
            side_effects=False,
            risk_level="read_only",
            provider_id=provider_id,
            capability_level=CAPABILITY_L0,
            requires_confirm=False,
            timeout_ms=30_000,
        ),
        ToolMeta(
            name="text.summarize",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}, "max_length": {"type": "integer"}},
                "required": ["text"],
            },
            side_effects=False,
            risk_level="read_only",
            provider_id=provider_id,
            capability_level=CAPABILITY_L0,
            requires_confirm=False,
            timeout_ms=60_000,
        ),
    ]


class ToolCatalog:
    """多 provider 聚合：按 preferred_provider_order 解析工具，同名取第一个。"""

    DEFAULT_PREFERRED_ORDER = ["builtin", "stub"]

    def __init__(self, preferred_provider_order: Optional[List[str]] = None) -> None:
        self._providers: Dict[str, Any] = {}  # provider_id -> ToolProvider
        self._preferred_provider_order: List[str] = (
            list(preferred_provider_order) if preferred_provider_order else list(self.DEFAULT_PREFERRED_ORDER)
        )

    def register_provider(self, provider_id: str, provider: ToolProvider) -> None:
        self._providers[provider_id] = provider

    def set_preferred_provider_order(self, order: List[str]) -> None:
        """配置 provider 优先级，同名工具时取顺序靠前的实现。"""
        self._preferred_provider_order = list(order)

    def get_provider(self, provider_id: str) -> Optional[ToolProvider]:
        return self._providers.get(provider_id)

    def get(self, name: str) -> Optional[ToolMeta]:
        """按 preferred_provider_order 返回第一个提供该 name 的 ToolMeta。"""
        for pid in self._preferred_provider_order:
            provider = self._providers.get(pid)
            if not provider:
                continue
            for meta in provider.list_tools():
                if meta.name == name:
                    return meta
        return None

    def list_tools(self) -> List[ToolMeta]:
        """聚合所有 provider 的工具，同名只保留 preferred 顺序下第一个。"""
        seen: set = set()
        out: List[ToolMeta] = []
        for pid in self._preferred_provider_order:
            provider = self._providers.get(pid)
            if not provider:
                continue
            for meta in provider.list_tools():
                if meta.name not in seen:
                    seen.add(meta.name)
                    out.append(meta)
        return out

    # 兼容旧用法：单 provider 时代 register(meta) / list_builtin
    def register(self, meta: ToolMeta) -> None:
        """仅当存在单 provider 且该 provider 支持 register 时有效；否则无操作。builtin/stub 由 provider 管理。"""
        pass

    def unregister(self, name: str) -> None:
        """测试用：从 catalog 解析中排除某工具需通过 provider 或 preferred_order 控制。"""
        pass

    def list_builtin(self) -> List[ToolMeta]:
        """兼容：返回 list_tools()。"""
        return self.list_tools()

    def close_providers(self) -> None:
        """关闭所有支持 close() 的 provider（如 MCPProvider），worker shutdown 时调用；可多次调用。"""
        for pid, provider in list(self._providers.items()):
            if hasattr(provider, "close") and callable(provider.close):
                try:
                    provider.close()
                except Exception:
                    pass


def _mcp_servers_from_env() -> Optional[List[Dict[str, Any]]]:
    """解析 MCP_SERVERS_JSON；未设置返回 None，无效 JSON 打 warning 后返回 None，有效返回 list（可为空）。
    每项：name([a-z0-9_]+)、cmd(非空 list)、cwd?、env?。非法项跳过并 warning，不拖死其余。"""
    raw = os.getenv("MCP_SERVERS_JSON")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        trunc = (raw[: MCP_SERVERS_JSON_RAW_TRUNCATE] + "…") if len(raw) > MCP_SERVERS_JSON_RAW_TRUNCATE else raw
        logger.warning("MCP_SERVERS_JSON invalid JSON, fallback to single-server or no MCP: raw=%s error=%s", trunc, e)
        return None
    if not isinstance(data, list):
        logger.warning("MCP_SERVERS_JSON root is not a list, fallback: type=%s", type(data).__name__)
        return None
    out: List[Dict[str, Any]] = []
    seen_names: set = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name or not isinstance(name, str):
            continue
        name = str(name).strip() or "srv"
        if not MCP_SERVER_NAME_PATTERN.match(name):
            logger.warning("MCP_SERVERS_JSON server name invalid (allowed [a-z0-9_]+), skipping: name=%r", name)
            continue
        if name in seen_names:
            logger.warning("MCP_SERVERS_JSON duplicate server name, skipping: name=%r", name)
            continue
        cmd = item.get("cmd")
        if cmd is None:
            logger.warning("MCP_SERVERS_JSON server missing cmd, skipping: name=%r", name)
            continue
        if isinstance(cmd, list):
            cmd = [str(x) for x in cmd if x is not None]
        elif isinstance(cmd, str):
            cmd = [cmd.strip()] if cmd.strip() else []
        else:
            logger.warning("MCP_SERVERS_JSON server cmd must be list or string, skipping: name=%r", name)
            continue
        if not cmd:
            logger.warning("MCP_SERVERS_JSON server cmd empty, skipping: name=%r", name)
            continue
        seen_names.add(name)
        entry: Dict[str, Any] = {"name": name, "cmd": cmd}
        if "cwd" in item:
            entry["cwd"] = item["cwd"] if item["cwd"] is None else str(item["cwd"])
        if "env" in item and item["env"] is not None and isinstance(item["env"], dict):
            entry["env"] = {str(k): str(v) for k, v in item["env"].items()}
        out.append(entry)
    return out


def _mcp_cmd_from_env() -> Optional[List[str]]:
    """从环境变量解析 MCP server cmd；无配置返回 None。"""
    cmd_str = os.getenv("MCP_SERVER_CMD")
    if not cmd_str or not cmd_str.strip():
        return None
    args: List[str] = []
    args_json = os.getenv("MCP_SERVER_ARGS_JSON")
    args_str = os.getenv("MCP_SERVER_ARGS")
    if args_json:
        try:
            args = json.loads(args_json)
            if not isinstance(args, list):
                args = []
        except (json.JSONDecodeError, TypeError):
            args = []
    elif args_str and args_str.strip():
        args = shlex.split(args_str.strip())
    return [cmd_str.strip()] + args


def _web_search_backend_from_env() -> Any:
    """根据 WEB_SEARCH_BACKEND 构造 backend：stub/ddg_html/searxng；未知值打 warning 并回退 stub。"""
    backend_name = (os.getenv("WEB_SEARCH_BACKEND") or "stub").strip().lower()
    if backend_name == "stub":
        from worker.tools.web_backends.stub import StubWebSearchBackend
        return StubWebSearchBackend()
    if backend_name == "ddg_html":
        from worker.tools.web_backends.ddg_html import DDGHtmlBackend
        return DDGHtmlBackend()
    if backend_name == "searxng":
        base_url = (os.getenv("SEARXNG_BASE_URL") or "").strip()
        if not base_url:
            raw_val = os.getenv("SEARXNG_BASE_URL")
            trunc = (str(raw_val)[:200] + "…") if raw_val is not None and len(str(raw_val)) > 200 else raw_val
            logger.warning(
                "WEB_SEARCH_BACKEND=searxng but SEARXNG_BASE_URL unset or empty (value=%r), fallback to stub",
                trunc if trunc is not None else "(unset)",
            )
            from worker.tools.web_backends.stub import StubWebSearchBackend
            return StubWebSearchBackend()
        api_key = (os.getenv("SEARXNG_API_KEY") or "").strip() or None
        from worker.tools.web_backends.searxng import SearxngBackend
        return SearxngBackend(base_url=base_url, api_key=api_key)
    logger.warning("WEB_SEARCH_BACKEND unknown value %r, fallback to stub", backend_name)
    from worker.tools.web_backends.stub import StubWebSearchBackend
    return StubWebSearchBackend()


def _web_search_timeout_ms() -> int:
    try:
        return max(1000, int(os.getenv("WEB_SEARCH_TIMEOUT_MS", "15000")))
    except (TypeError, ValueError):
        return 15000


def _searxng_timeout_ms() -> int:
    """Searxng 超时：SEARXNG_TIMEOUT_MS 优先，否则复用 WEB_SEARCH_TIMEOUT_MS。"""
    raw = os.getenv("SEARXNG_TIMEOUT_MS")
    if raw is not None and str(raw).strip():
        try:
            return max(1000, int(raw))
        except (TypeError, ValueError):
            pass
    return _web_search_timeout_ms()


def _web_fetch_backend_from_env() -> Any:
    """根据 WEB_FETCH_BACKEND 构造 fetch backend：stub / httpx；未知值打 warning 回退 stub。"""
    backend_name = (os.getenv("WEB_FETCH_BACKEND") or "stub").strip().lower()
    if backend_name in ("", "stub"):
        from worker.tools.web_backends.fetch_stub import StubWebFetchBackend
        return StubWebFetchBackend()
    if backend_name == "httpx":
        from worker.tools.web_backends.http_fetch import HttpxFetchBackend
        return HttpxFetchBackend()
    logger.warning("WEB_FETCH_BACKEND unknown value %r, fallback to stub", backend_name)
    from worker.tools.web_backends.fetch_stub import StubWebFetchBackend
    return StubWebFetchBackend()


def _web_fetch_timeout_ms() -> int:
    """WEB_FETCH_TIMEOUT_MS 优先，否则复用 WEB_SEARCH_TIMEOUT_MS。"""
    raw = os.getenv("WEB_FETCH_TIMEOUT_MS")
    if raw is not None and str(raw).strip():
        try:
            return max(1000, int(raw))
        except (TypeError, ValueError):
            pass
    return _web_search_timeout_ms()


# 延迟导入避免循环
def _default_catalog_factory() -> ToolCatalog:
    from worker.tools.provider import BuiltinProvider, StubProvider
    from worker.tools.web_provider import WebProvider

    order: List[str] = ["web", "builtin", "stub"]
    catalog = ToolCatalog(preferred_provider_order=order)
    search_backend = _web_search_backend_from_env()
    fetch_backend = _web_fetch_backend_from_env()
    web_timeout_ms = (
        _searxng_timeout_ms()
        if getattr(search_backend, "backend_id", None) == "searxng"
        else _web_search_timeout_ms()
    )
    fetch_timeout_ms = _web_fetch_timeout_ms()
    catalog.register_provider(
        "web",
        WebProvider(
            search_backend=search_backend,
            fetch_backend=fetch_backend,
            timeout_ms=web_timeout_ms,
            fetch_timeout_ms=fetch_timeout_ms,
        ),
    )
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("stub", StubProvider())

    servers = _mcp_servers_from_env()
    if servers is not None:
        # 2.2 v0.2：多 MCP server，MCP_SERVERS_JSON 优先
        from worker.tools.mcp_provider import MCPProvider
        mcp_ids: List[str] = []
        for s in servers:
            name = s["name"]
            provider_id = f"mcp_{name}"
            cmd = s["cmd"]
            cwd = s.get("cwd")
            env = s.get("env")
            catalog.register_provider(provider_id, MCPProvider(server_name=name, provider_id=provider_id, cmd=cmd, cwd=cwd, env=env))
            mcp_ids.append(provider_id)
        if mcp_ids:
            order = ["web", "builtin"] + mcp_ids + ["stub"]
            catalog.set_preferred_provider_order(order)
    else:
        cmd = _mcp_cmd_from_env()
        if cmd:
            from worker.tools.mcp_provider import MCPProvider
            name = os.getenv("MCP_SERVER_NAME", "srv").strip() or "srv"
            provider_id = f"mcp_{name}"
            cwd = os.getenv("MCP_SERVER_CWD")
            catalog.register_provider(provider_id, MCPProvider(server_name=name, provider_id=provider_id, cmd=cmd, cwd=cwd or None, env=None))
            order = ["web", "builtin", provider_id, "stub"]
            catalog.set_preferred_provider_order(order)

    return catalog


_default_catalog: Optional[ToolCatalog] = None


def get_default_catalog() -> ToolCatalog:
    global _default_catalog
    if _default_catalog is None:
        _default_catalog = _default_catalog_factory()
        atexit.register(_default_catalog.close_providers)
    return _default_catalog
