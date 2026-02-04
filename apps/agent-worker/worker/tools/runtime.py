"""ToolRuntime.invoke(name, args, ctx): one step per call, meta only args_preview/result_preview."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from worker.task_context import TaskContext
from worker.tools.catalog import ToolCatalog, get_default_catalog
from worker.tools.errors import ToolNotFoundError

PREVIEW_MAX = 200


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
    """通过 Catalog 多 provider 调用：按 preferred_provider_order 解析工具，step 内记录 args/result preview。"""

    def __init__(self, catalog: Optional[ToolCatalog] = None) -> None:
        self._catalog = catalog or get_default_catalog()

    def invoke(
        self,
        ctx: TaskContext,
        name: str,
        args: Dict[str, Any],
        *,
        llm: Optional[Any] = None,
    ) -> Any:
        """Run tool in one step; step name = tool.{name}; meta = args_preview, result_preview, provider_id, risk_level."""
        step_name = f"tool.{name}"
        with ctx.step(step_name) as step_meta:
            meta = self._catalog.get(name)
            if not meta:
                raise ToolNotFoundError(name, "not in catalog")
            provider = self._catalog.get_provider(meta.provider_id)
            if not provider:
                raise ToolNotFoundError(name, f"provider {meta.provider_id} not registered")
            step_meta["args_preview"] = _preview(args)
            step_meta["tool_name"] = name
            step_meta["provider_id"] = meta.provider_id
            step_meta["risk_level"] = meta.risk_level
            step_meta["capability_level"] = meta.capability_level
            try:
                result = provider.invoke(name, args, ctx, llm=llm)
            except Exception:
                step_meta["result_preview"] = "(error)"
                raise
            step_meta["result_preview"] = _preview(result)
            return result
