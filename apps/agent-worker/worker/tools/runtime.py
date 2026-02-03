"""ToolRuntime.invoke(name, args, ctx): one step per call, meta only args_preview/result_preview."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from worker.task_context import TaskContext
from worker.tools.builtin_llm import text_summarize_impl
from worker.tools.builtin_stub import web_fetch_stub, web_search_stub
from worker.tools.catalog import ToolCatalog, get_default_catalog

PREVIEW_MAX = 200


class ToolNotFoundError(ValueError):
    """Tool not in catalog or no implementation; error.code = ToolNotFound for UI/debug."""

    code: str = "ToolNotFound"

    def __init__(self, name: str, detail: str = "") -> None:
        self.name = name
        self.detail = detail
        super().__init__(f"Tool not found: {name}" + (f" ({detail})" if detail else ""))


def _preview(obj: Any, limit: int = PREVIEW_MAX) -> str:
    """Unified preview for steps.meta (args_preview / result_preview). Never raises."""
    if obj is None:
        return ""
    if limit <= 0:
        return ""
    if isinstance(obj, (str, int, float, bool)):
        s = str(obj)[:limit]
        return s + "…" if len(str(obj)) > limit else s
    try:
        raw = json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        try:
            raw = str(obj)
        except Exception:
            return "<unable to preview>"
    if len(raw) > limit:
        raw = raw[:limit] + "…"
    return raw


class ToolRuntime:
    """Invoke tools with one ctx.step per call; meta only args_preview and result_preview."""

    def __init__(self, catalog: Optional[ToolCatalog] = None) -> None:
        self._catalog = catalog or get_default_catalog()
        self._impls: Dict[str, Callable[..., Any]] = {
            "web.search": web_search_stub,
            "web.fetch": web_fetch_stub,
        }

    def register_impl(self, name: str, impl: Callable[..., Any]) -> None:
        self._impls[name] = impl

    def invoke(
        self,
        ctx: TaskContext,
        name: str,
        args: Dict[str, Any],
        *,
        llm: Optional[Any] = None,
    ) -> Any:
        """Run tool in one step; step name = tool.{name}; meta = args_preview, result_preview. Raises on error."""
        step_name = f"tool.{name}"
        with ctx.step(step_name) as step_meta:
            meta = self._catalog.get(name)
            if not meta:
                raise ToolNotFoundError(name, "not in catalog")
            impl = self._impls.get(name)
            if not impl:
                raise ToolNotFoundError(name, "no implementation")
            step_meta["args_preview"] = _preview(args)
            step_meta["tool_name"] = name
            step_meta["risk_level"] = meta.risk_level
            try:
                if name == "text.summarize":
                    result = text_summarize_impl(llm, args) if llm else {"summary": "(no llm)"}
                else:
                    result = impl(args)
            except Exception:
                step_meta["result_preview"] = "(error)"
                raise
            step_meta["result_preview"] = _preview(result)
            return result
