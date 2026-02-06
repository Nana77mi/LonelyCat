"""PR4: GET /skills、POST /skills/{id}/invoke。MCP list_tools ← GET /skills，call_tool ← POST /skills/{id}/invoke。"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.api.sandbox import (
    ExecBody,
    InputItem,
    SandboxExecBody,
    TaskRefBody,
    execute_sandbox_body,
    get_db,
)
from app.services.skills.loader import is_skills_root_configured, load_manifest, list_skills

router = APIRouter(tags=["skills"])


@router.get("", response_model=list)
def get_skills_list() -> list:
    """
    列出所有技能（来自 repo 根 skills/ 目录）。供 MCP list_tools 等使用。
    返回每项：id, name, description, runtime, interface, permissions, limits。
    未配置 skills 根（无 REPO_ROOT/SKILLS_ROOT 且无有效 skills/_schema）时返回 503 并提示。
    """
    skills_list = list_skills()
    if not skills_list and not is_skills_root_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SKILLS_NOT_CONFIGURED",
                "message": "Skills root not configured. Set REPO_ROOT or SKILLS_ROOT, or run from repo root with skills/_schema/manifest.schema.json present.",
            },
        )
    return skills_list


class SkillInvokeBody(BaseModel):
    """POST /skills/{id}/invoke 请求体：project_id 必填，其余为技能输入与可选 task_ref。"""
    model_config = ConfigDict(extra="allow")  # script, code, timeout_ms 等按 manifest.interface.inputs

    project_id: str
    task_id: str | None = None
    conversation_id: str | None = None


def _build_exec_from_manifest(skill_id: str, manifest: dict[str, Any], body: dict[str, Any]) -> SandboxExecBody:
    """
    根据 manifest 与 invoke body 构建 SandboxExecBody。
    Policy：manifest.limits 放入 manifest_limits（合并入 policy），仅请求层 overrides 放入 policy_overrides。
    Phase1 固定 command=bash/python，不依赖镜像 ENTRYPOINT；校验 manifest runtime.entrypoint 为 bash/python。
    """
    runtime = manifest.get("runtime") or {}
    limits = manifest.get("limits") or {}
    # manifest limits 合并入 policy（runner 内 default ← settings ← manifest_limits ← policy_overrides）
    manifest_limits: dict[str, Any] = dict(limits) if limits else {}
    # 仅请求层 overrides（如 body.timeout_ms 更严）
    policy_overrides: dict[str, Any] = {}
    if body.get("timeout_ms") is not None:
        policy_overrides["timeout_ms"] = int(body["timeout_ms"])

    task_ref = TaskRefBody(task_id=body.get("task_id"), conversation_id=body.get("conversation_id"))
    inputs: list[InputItem] = []

    if skill_id == "shell.run":
        entrypoint = (runtime.get("entrypoint") or "bash").strip().lower()
        if entrypoint != "bash":
            raise HTTPException(status_code=400, detail={"code": "INVALID_MANIFEST", "message": "shell.run 的 runtime.entrypoint 须为 bash"})
        script = body.get("script")
        if script is None or (isinstance(script, str) and not script.strip()):
            raise HTTPException(status_code=400, detail={"code": "INVALID_INPUT", "message": "shell.run 需要 script"})
        return SandboxExecBody(
            project_id=body["project_id"],
            skill_id=skill_id,
            exec=ExecBody(kind="shell", command="bash", args=["-lc", str(script).strip()], cwd="work"),
            inputs=inputs,
            manifest_limits=manifest_limits,
            policy_overrides=policy_overrides or None,
            task_ref=task_ref,
        )

    if skill_id == "python.run":
        entrypoint = (runtime.get("entrypoint") or "python").strip().lower()
        if entrypoint != "python":
            raise HTTPException(status_code=400, detail={"code": "INVALID_MANIFEST", "message": "python.run 的 runtime.entrypoint 须为 python"})
        code = body.get("code")
        script_path = body.get("script_path")
        if code is not None and str(code).strip():
            args = ["-c", str(code).strip()]
        elif script_path:
            raw = str(script_path).strip().replace("\\", "/").lstrip("/")
            if not raw:
                raise HTTPException(status_code=400, detail={"code": "INVALID_INPUT", "message": "script_path 不能为空"})
            normalized = os.path.normpath(raw).replace("\\", "/")
            if normalized.startswith("..") or ".." in normalized or os.path.isabs(normalized):
                raise HTTPException(status_code=400, detail={"code": "INVALID_INPUT", "message": "script_path 不允许路径穿越或绝对路径"})
            args = [f"/workspace/inputs/{normalized}"]
        else:
            raise HTTPException(status_code=400, detail={"code": "INVALID_INPUT", "message": "python.run 需要 code 或 script_path"})
        return SandboxExecBody(
            project_id=body["project_id"],
            skill_id=skill_id,
            exec=ExecBody(kind="python", command="python", args=args, cwd="work"),
            inputs=inputs,
            manifest_limits=manifest_limits,
            policy_overrides=policy_overrides or None,
            task_ref=task_ref,
        )

    # 通用：Phase1 仅支持 shell.run / python.run
    raise HTTPException(status_code=400, detail={"code": "UNSUPPORTED_SKILL", "message": f"暂不支持的 skill: {skill_id}"})


@router.post("/{skill_id}/invoke", response_model=dict)
def post_skill_invoke(
    skill_id: str,
    request: Request,
    body: SkillInvokeBody,
    db=Depends(get_db),
) -> dict:
    """
    按技能 manifest 执行沙箱。请求体含 project_id、可选 task_id/conversation_id 及技能输入（如 script、code）。
    等价于根据 manifest 构造 POST /sandbox/execs 并执行。
    """
    try:
        manifest = load_manifest(skill_id)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"skill manifest invalid: {e!s}")
    if not manifest:
        raise HTTPException(status_code=404, detail="skill not found")
    body_dict = body.model_dump(exclude_none=False)
    body_dict.setdefault("project_id", body.project_id)
    body_dict.setdefault("task_id", body.task_id)
    body_dict.setdefault("conversation_id", body.conversation_id)
    try:
        sandbox_body = _build_exec_from_manifest(skill_id, manifest, body_dict)
    except HTTPException:
        raise
    return execute_sandbox_body(sandbox_body, request, db)
