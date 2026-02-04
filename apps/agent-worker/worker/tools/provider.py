"""ToolProvider 接口与内置实现：BuiltinProvider、StubProvider（Phase 2.1）."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from worker.task_context import TaskContext
from worker.tools.builtin_llm import text_summarize_impl
from worker.tools.builtin_stub import web_fetch_stub, web_search_stub
from worker.tools.catalog import ToolMeta, _builtin_tool_meta


class ToolProvider(Protocol):
    """Provider 接口：list_tools + invoke，由 Catalog 按 preferred_provider_order 聚合。"""

    def list_tools(self) -> List[ToolMeta]:
        """返回该 provider 提供的工具元数据列表。"""
        ...

    def invoke(
        self,
        tool_name: str,
        args: Dict[str, Any],
        ctx: TaskContext,
        *,
        llm: Optional[Any] = None,
    ) -> Any:
        """执行工具，返回结果。由 ToolRuntime 在 step 内调用。"""
        ...


class BuiltinProvider:
    """内置工具：web.search / web.fetch / text.summarize，当前 search/fetch 用 stub 实现。"""

    PROVIDER_ID = "builtin"

    def list_tools(self) -> List[ToolMeta]:
        return _builtin_tool_meta(provider_id=self.PROVIDER_ID)

    def invoke(
        self,
        tool_name: str,
        args: Dict[str, Any],
        ctx: TaskContext,
        *,
        llm: Optional[Any] = None,
    ) -> Any:
        if tool_name == "web.search":
            return web_search_stub(args)
        if tool_name == "web.fetch":
            return web_fetch_stub(args)
        if tool_name == "text.summarize":
            return text_summarize_impl(llm, args) if llm else {"summary": "(no llm)"}
        raise ValueError(f"Unknown tool: {tool_name}")


class StubProvider:
    """开发用 stub：与 builtin 同名工具，provider_id=stub，纯 stub 实现。"""

    PROVIDER_ID = "stub"

    def list_tools(self) -> List[ToolMeta]:
        return _builtin_tool_meta(provider_id=self.PROVIDER_ID)

    def invoke(
        self,
        tool_name: str,
        args: Dict[str, Any],
        ctx: TaskContext,
        *,
        llm: Optional[Any] = None,
    ) -> Any:
        if tool_name == "web.search":
            return web_search_stub(args)
        if tool_name == "web.fetch":
            return web_fetch_stub(args)
        if tool_name == "text.summarize":
            return {"summary": "(stub, no llm)"} if not llm else text_summarize_impl(llm, args)
        raise ValueError(f"Unknown tool: {tool_name}")


class FailingProvider:
    """测试用：list_tools 与 builtin 相同，invoke 始终抛错，用于验证工具失败时 output schema。"""

    PROVIDER_ID = "builtin"

    def list_tools(self) -> List[ToolMeta]:
        return _builtin_tool_meta(provider_id=self.PROVIDER_ID)

    def invoke(
        self,
        tool_name: str,
        args: Dict[str, Any],
        ctx: TaskContext,
        *,
        llm: Optional[Any] = None,
    ) -> Any:
        raise RuntimeError("simulated tool failure for tests")


class SearchOnlyProvider:
    """测试用：仅提供 web.search，用于验证 web.fetch 未注册时 ToolNotFound。"""

    PROVIDER_ID = "search_only"

    def list_tools(self) -> List[ToolMeta]:
        return [m for m in _builtin_tool_meta(provider_id=self.PROVIDER_ID) if m.name == "web.search"]

    def invoke(
        self,
        tool_name: str,
        args: Dict[str, Any],
        ctx: TaskContext,
        *,
        llm: Optional[Any] = None,
    ) -> Any:
        if tool_name == "web.search":
            return web_search_stub(args)
        raise ValueError(f"Unknown tool: {tool_name}")
