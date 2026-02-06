"""Sandbox 执行 API：POST /sandbox/execs。见 docs/spec/sandbox.md。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.settings import get_current_settings
from app.db import SessionLocal
from app.services.sandbox.docker_health import get_sandbox_health
from app.services.sandbox.errors import InvalidArgumentError, PolicyDeniedError, SandboxRuntimeError
from app.services.sandbox.runner_docker import run_sandbox_exec
from app.services.sandbox.schemas import SandboxExecInput, SandboxExecRequest


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


router = APIRouter(tags=["sandbox"])


@router.get("/health", response_model=dict)
def get_sandbox_health_endpoint(db: Session = Depends(get_db)) -> dict:
    """
    沙箱诊断：runtime_mode、workspace_root_native、docker_cli_path、
    docker_version、docker_context、writable_check。便于 Win/WSL 联调。
    """
    settings = get_current_settings(db)
    return get_sandbox_health(settings)


class ExecBody(BaseModel):
    kind: str
    command: str
    args: list[str]
    cwd: str = "work"
    env: dict[str, str] | None = None


class InputItem(BaseModel):
    path: str
    content: str


class TaskRefBody(BaseModel):
    task_id: str | None = None
    conversation_id: str | None = None


class SandboxExecBody(BaseModel):
    project_id: str
    skill_id: str | None = None
    exec: ExecBody
    inputs: list[InputItem] = []
    policy_overrides: dict[str, Any] | None = None
    task_ref: TaskRefBody | None = None


@router.post("/execs", response_model=dict)
def post_sandbox_execs(body: SandboxExecBody, db: Session = Depends(get_db)) -> dict:
    """
    执行沙箱任务。policy 校验、normpath 防穿越、挂载仅三模板路径。
    请求体：project_id, skill_id, exec (kind, command, args, cwd, env), inputs[], policy_overrides?, task_ref?。
    """
    settings = get_current_settings(db)
    req = SandboxExecRequest(
        project_id=body.project_id,
        skill_id=body.skill_id,
        exec_kind=body.exec.kind,
        command=body.exec.command,
        args=body.exec.args,
        cwd=body.exec.cwd or "work",
        env=body.exec.env,
        inputs=[SandboxExecInput(path=x.path, content=x.content) for x in body.inputs],
        policy_overrides=body.policy_overrides,
        task_id=body.task_ref.task_id if body.task_ref else None,
        conversation_id=body.task_ref.conversation_id if body.task_ref else None,
    )
    try:
        resp = run_sandbox_exec(settings, req)
    except PolicyDeniedError as e:
        raise HTTPException(status_code=403, detail=e.to_reason())
    except InvalidArgumentError as e:
        raise HTTPException(status_code=400, detail=e.to_reason())
    except SandboxRuntimeError as e:
        raise HTTPException(status_code=500, detail=e.to_reason())
    return {
        "exec_id": resp.exec_id,
        "status": resp.status,
        "exit_code": resp.exit_code,
        "artifacts_dir": resp.artifacts_dir,
        "stdout_path": resp.stdout_path,
        "stderr_path": resp.stderr_path,
        "stdout_truncated": resp.stdout_truncated,
        "stderr_truncated": resp.stderr_truncated,
        "error_reason": resp.error_reason,
    }  # artifacts_dir/stdout_path/stderr_path 为相对路径
