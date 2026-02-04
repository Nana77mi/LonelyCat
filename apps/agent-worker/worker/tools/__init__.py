"""ToolCatalog / ToolRuntime v1: multi-provider, MCPProvider (Phase 2.1/2.2)."""

from worker.tools.catalog import ToolCatalog, ToolMeta
from worker.tools.errors import ToolNotFoundError
from worker.tools.runtime import ToolRuntime

__all__ = ["ToolCatalog", "ToolMeta", "ToolNotFoundError", "ToolRuntime", "MCPProvider"]

# MCPProvider 懒加载，避免未用 MCP 时强依赖
def __getattr__(name: str):
    if name == "MCPProvider":
        from worker.tools.mcp_provider import MCPProvider
        return MCPProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
