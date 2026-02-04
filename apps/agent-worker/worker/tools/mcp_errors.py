"""MCP 错误码：SpawnFailed、Timeout、ConnectionError（Phase 2.2 v0.1）."""

from __future__ import annotations


class MCPSpawnFailedError(ValueError):
    """子进程启动失败；error.code = SpawnFailed。"""

    code: str = "SpawnFailed"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__("MCP spawn failed" + (f" ({detail})" if detail else ""))


class MCPTimeoutError(ValueError):
    """请求超时；error.code = Timeout。"""

    code: str = "Timeout"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__("MCP request timeout" + (f" ({detail})" if detail else ""))


class MCPConnectionError(ValueError):
    """进程挂/管道断/协议错误；error.code = ConnectionError。"""

    code: str = "ConnectionError"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__("MCP connection error" + (f" ({detail})" if detail else ""))
