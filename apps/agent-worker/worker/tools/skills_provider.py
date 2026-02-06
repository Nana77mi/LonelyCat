"""PR5: Skills 作为 ToolProvider — list_tools ← GET /skills，invoke ← POST /skills/{id}/invoke。"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from worker.task_context import TaskContext
from worker.tools.catalog import CAPABILITY_L2, ToolMeta

logger = logging.getLogger(__name__)

SKILL_TOOL_PREFIX = "skill."
DEFAULT_SKILLS_TIMEOUT_MS = 30_000

# 开关：SKILLS_LIST_FALLBACK=1 时 GET /skills 失败仍返回占位 python.run/shell.run（默认关闭，避免掩盖真实错误）
def _fallback_enabled() -> bool:
    return os.environ.get("SKILLS_LIST_FALLBACK", "").strip() == "1"


class SkillsListError(RuntimeError):
    """GET /skills 失败时抛出，message 含 base_url 与原因，便于排查。"""
    def __init__(self, base_url: str, reason: str) -> None:
        self.base_url = base_url
        self.reason = reason
        super().__init__(f"GET {base_url}/skills failed: {reason}")


def _skill_tool_name(skill_id: str) -> str:
    return f"{SKILL_TOOL_PREFIX}{skill_id}"


def _fallback_tool_metas() -> List[ToolMeta]:
    """仅当 SKILLS_LIST_FALLBACK=1 时使用：返回 python.run/shell.run 占位。"""
    schemas = {
        "python.run": {"type": "object", "properties": {"code": {"type": "string"}, "project_id": {"type": "string"}, "timeout_ms": {"type": "integer"}}},
        "shell.run": {"type": "object", "properties": {"script": {"type": "string"}, "project_id": {"type": "string"}, "timeout_ms": {"type": "integer"}}},
    }
    return [
        ToolMeta(
            name=_skill_tool_name(sid),
            input_schema=schemas.get(sid, {"type": "object"}),
            side_effects=True,
            risk_level="write",
            provider_id="skills",
            capability_level=CAPABILITY_L2,
            requires_confirm=False,
            timeout_ms=60_000,
        )
        for sid in ("python.run", "shell.run")
    ]


def _skill_id_from_tool_name(tool_name: str) -> Optional[str]:
    if not tool_name.startswith(SKILL_TOOL_PREFIX):
        return None
    return tool_name[len(SKILL_TOOL_PREFIX) :].strip() or None


def _tool_meta_from_skill(skill: Dict[str, Any]) -> ToolMeta:
    sid = skill.get("id") or "unknown"
    name = _skill_tool_name(sid)
    interface = skill.get("interface") or {}
    inputs = interface.get("inputs") or {}
    if isinstance(inputs, list):
        input_schema = {"type": "object"}
    else:
        input_schema = inputs if isinstance(inputs, dict) else {"type": "object"}
    limits = skill.get("limits") or {}
    timeout_ms = limits.get("timeout_ms") or DEFAULT_SKILLS_TIMEOUT_MS
    return ToolMeta(
        name=name,
        input_schema=input_schema,
        side_effects=True,
        risk_level="write",
        provider_id="skills",
        capability_level=CAPABILITY_L2,
        requires_confirm=False,
        timeout_ms=timeout_ms,
    )


class SkillsProvider:
    """
    ToolProvider：list_tools 来自 core-api GET /skills，invoke 调用 POST /skills/{id}/invoke。
    工具名格式 skill.<skill_id>。GET 失败时默认抛出 SkillsListError(base_url, reason)；设 SKILLS_LIST_FALLBACK=1 可改为返回占位工具。
    """

    PROVIDER_ID = "skills"

    def __init__(
        self,
        base_url: str,
        *,
        client: Optional[Any] = None,
        timeout_sec: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout_sec

    def _fail_or_fallback(self, reason: str) -> List[ToolMeta]:
        if _fallback_enabled():
            logger.warning("skills list_tools %s (fallback enabled)", reason)
            return _fallback_tool_metas()
        raise SkillsListError(self._base, reason)

    def list_tools(self) -> List[ToolMeta]:
        """GET /skills 映射为 ToolMeta；失败时默认抛 SkillsListError 含 base_url+原因，或 SKILLS_LIST_FALLBACK=1 时返回占位。"""
        try:
            if self._client is not None:
                resp = self._client.get(f"{self._base}/skills", timeout=self._timeout)
            else:
                import httpx
                with httpx.Client(timeout=self._timeout) as c:
                    resp = c.get(f"{self._base}/skills")
        except Exception as e:
            return self._fail_or_fallback(str(e))
        if resp.status_code != 200:
            return self._fail_or_fallback(f"HTTP {resp.status_code}")
        try:
            _json = getattr(resp, "json", None)
            data = _json() if callable(_json) else _json
        except Exception as e:
            return self._fail_or_fallback(f"json parse error: {e}")
        if not isinstance(data, list):
            return self._fail_or_fallback("response not a list")
        if len(data) == 0:
            return self._fail_or_fallback("empty list (skills root not configured?)")
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            sid = item.get("id")
            if not sid or not isinstance(sid, str):
                continue
            result.append(_tool_meta_from_skill(item))
        return result if result else self._fail_or_fallback("empty list after parse")

    def invoke(
        self,
        tool_name: str,
        args: Dict[str, Any],
        ctx: TaskContext,
        *,
        llm: Optional[Any] = None,
    ) -> Any:
        """POST /skills/{skill_id}/invoke；project_id 来自 args 或 ctx.run.input_json.conversation_id。"""
        skill_id = _skill_id_from_tool_name(tool_name)
        if not skill_id:
            raise ValueError(f"Unknown tool: {tool_name} (expected skill.<id>)")
        allowed_ids = {
            t.name[len(SKILL_TOOL_PREFIX) :]
            for t in self.list_tools()
            if t.name.startswith(SKILL_TOOL_PREFIX)
        }
        if skill_id not in allowed_ids:
            raise ValueError(f"Unknown skill tool: {tool_name} (not in GET /skills)")
        project_id = args.get("project_id")
        if not project_id and ctx.run and getattr(ctx.run, "input_json", None):
            project_id = (ctx.run.input_json or {}).get("conversation_id")
        if not project_id and ctx.run and getattr(ctx.run, "id", None):
            project_id = str(ctx.run.id)
        if not project_id:
            raise ValueError("project_id required (or set conversation_id in run input_json)")
        body = dict(args)
        body["project_id"] = project_id

        if self._client is not None:
            resp = self._client.post(
                f"{self._base}/skills/{skill_id}/invoke",
                json=body,
                timeout=self._timeout,
            )
        else:
            try:
                import httpx
                with httpx.Client(timeout=self._timeout) as c:
                    resp = c.post(f"{self._base}/skills/{skill_id}/invoke", json=body)
            except Exception as e:
                logger.warning("skills invoke %s failed: %s", skill_id, e)
                raise
        if resp.status_code >= 400:
            _json = getattr(resp, "json", None)
            try:
                detail = _json() if callable(_json) else (_json or {})
            except Exception:
                detail = {"message": getattr(resp, "text", str(resp))}
            raise RuntimeError(f"skills invoke {skill_id} failed: {resp.status_code} {detail}")
        _json = getattr(resp, "json", None)
        if callable(_json):
            try:
                return _json()
            except Exception:
                return {"result": getattr(resp, "text", "")}
        return _json or {"result": getattr(resp, "text", "")}