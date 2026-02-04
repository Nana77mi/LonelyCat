"""MCPProvider: MCP 作为 ToolProvider 接入，命名空间前缀、list_tools 降级、close（Phase 2.2）."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from worker.task_context import TaskContext
from worker.tools.catalog import CAPABILITY_L0, ToolMeta

logger = logging.getLogger(__name__)

MCP_TOOL_PREFIX = "mcp."
MCP_LIST_TOOLS_FAILED = "mcp.list_tools.failed"
DEFAULT_MCP_TIMEOUT_MS = 30_000


class MCPProviderClosedError(ValueError):
    """MCPProvider 已关闭时 invoke 抛出；error.code = ProviderClosed 供 step 落码。"""

    code: str = "ProviderClosed"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__("MCPProvider is closed" + (f" ({detail})" if detail else ""))


def _mcp_tool_name(server_name: str, raw_name: str) -> str:
    """工具名加前缀：mcp.<server_name>.<raw_name>。"""
    return f"{MCP_TOOL_PREFIX}{server_name}.{raw_name}"


def _strip_mcp_prefix(server_name: str, prefixed_name: str) -> Optional[str]:
    """从 mcp.<server_name>.<raw> 剥出 raw；不匹配则返回 None。"""
    prefix = f"{MCP_TOOL_PREFIX}{server_name}."
    if not prefixed_name.startswith(prefix):
        return None
    return prefixed_name[len(prefix) :]


def _tool_meta_from_mcp(server_name: str, provider_id: str, raw: Dict[str, Any]) -> ToolMeta:
    """将 MCP 返回的 tool 转为 ToolMeta，name 带前缀。"""
    raw_name = raw.get("name") or "unknown"
    name = _mcp_tool_name(server_name, raw_name)
    input_schema = raw.get("inputSchema") or raw.get("input_schema") or {"type": "object"}
    if isinstance(input_schema, list):
        input_schema = {"type": "object"}
    return ToolMeta(
        name=name,
        input_schema=input_schema,
        side_effects=raw.get("side_effects", False) or raw.get("sideEffects", False),
        risk_level="unknown",
        provider_id=provider_id,
        capability_level=CAPABILITY_L0,
        requires_confirm=bool(raw.get("side_effects") or raw.get("sideEffects")),
        timeout_ms=raw.get("timeout_ms") or raw.get("timeoutMs") or DEFAULT_MCP_TIMEOUT_MS,
    )


def _normalize_call_result(result: Any) -> Dict[str, Any]:
    """将 MCP call_tool 返回归一为 dict，便于 step result_preview。"""
    if isinstance(result, dict):
        return result
    if hasattr(result, "content") and result.content:
        texts = []
        for c in result.content:
            if isinstance(c, dict):
                if c.get("type") == "text" and "text" in c:
                    texts.append(c["text"])
            elif getattr(c, "type", None) == "text" and getattr(c, "text", None):
                texts.append(c.text)
        return {"content": result.content, "text": "\n".join(texts)} if texts else {"content": result.content}
    return {"result": result}


class MCPProvider:
    """MCP 作为 ToolProvider：工具名强制前缀 mcp.<server_name>.<tool_name>，list_tools 永远不抛（降级为空+日志），close 可调用。"""

    def __init__(
        self,
        server_name: str,
        provider_id: Optional[str] = None,
        *,
        client: Optional[Any] = None,
        cmd: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        self.server_name = server_name
        self.provider_id = provider_id or f"mcp_{server_name}"
        self._closed = False
        if client is not None:
            self._client = client
        elif cmd is not None:
            from worker.tools.mcp_stdio_client import MCPStdioClient
            self._client = MCPStdioClient(cmd=cmd, cwd=cwd, env=env)
        else:
            self._client = None

    def list_tools(self, timeout_ms: Optional[int] = None) -> List[ToolMeta]:
        """返回带前缀的 ToolMeta 列表；任何异常一律降级为空并打 mcp.list_tools.failed，永不抛。"""
        if self._closed or self._client is None:
            return []
        try:
            t = timeout_ms if timeout_ms is not None else DEFAULT_MCP_TIMEOUT_MS
            try:
                raw_list = self._client.list_tools(timeout_ms=t)
            except TypeError:
                raw_list = self._client.list_tools()
        except Exception as e:
            logger.warning("%s server_name=%s error=%s", MCP_LIST_TOOLS_FAILED, self.server_name, e)
            return []
        out: List[ToolMeta] = []
        for raw in raw_list or []:
            if isinstance(raw, dict):
                meta = _tool_meta_from_mcp(self.server_name, self.provider_id, raw)
                out.append(meta)
        return out

    def invoke(
        self,
        tool_name: str,
        args: Dict[str, Any],
        ctx: TaskContext,
        *,
        llm: Optional[Any] = None,
    ) -> Any:
        """执行工具：tool_name 须为 mcp.<server_name>.<raw_name>，向 MCP 传裸名。"""
        raw_name = _strip_mcp_prefix(self.server_name, tool_name)
        if raw_name is None:
            raise ValueError(f"Tool name not from this provider: {tool_name}")
        if self._closed:
            raise MCPProviderClosedError()
        if self._client is None:
            raise MCPProviderClosedError("no client")
        t = DEFAULT_MCP_TIMEOUT_MS
        try:
            result = self._client.call_tool(raw_name, args or {}, timeout_ms=t)
        except TypeError:
            result = self._client.call_tool(raw_name, args or {})
        return _normalize_call_result(result)

    def close(self) -> None:
        """关闭 provider，释放 MCP 子进程/连接；可多次调用。"""
        self._closed = True
        if getattr(self._client, "close", None) and callable(self._client.close):
            try:
                self._client.close()
            except Exception:
                pass
