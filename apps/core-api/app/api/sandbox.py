"""Sandbox 执行 API：POST/GET /sandbox/execs、GET execs/{id}、GET execs/{id}/artifacts。见 docs/spec/sandbox.md PR3。"""
from __future__ import annotations

import json
import subprocess
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.settings import get_current_settings
from app.db import SessionLocal, SandboxExecRecord, SandboxExecStatus
from app.services.sandbox.docker_health import get_sandbox_health
from app.services.sandbox.errors import InvalidArgumentError, PolicyDeniedError, SandboxRuntimeError
from app.services.sandbox.path_adapter import HostPathAdapter
from app.services.sandbox.runner_docker import run_sandbox_exec
from app.services.sandbox.schemas import SandboxExecInput, SandboxExecRequest


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _parse_json(s: str | None) -> Any:
    if not s or not s.strip():
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


router = APIRouter(tags=["sandbox"])


@router.get("/health", response_model=dict)
def get_sandbox_health_endpoint(
    db: Session = Depends(get_db),
    probe: int = Query(0, description="1=执行轻量探针 docker run ... -lc 'true'，排障用，默认不跑"),
) -> dict:
    """
    沙箱诊断：runtime_mode、workspace_root_native、docker_*、platform、writable_check。
    ?probe=1 时额外执行镜像可运行探针（timeout 5s），返回 probe_run、probe_ok、probe_error。
    """
    settings = get_current_settings(db)
    out = get_sandbox_health(settings)
    if probe != 1:
        return out
    cli_path = (out.get("docker_cli_path") or "docker").strip() or "docker"
    try:
        r = subprocess.run(
            [cli_path, "run", "--rm", "--entrypoint", "bash", "lonelycat-sandbox:py312", "-lc", "true"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        out["probe_run"] = True
        out["probe_ok"] = r.returncode == 0
        out["probe_error"] = None if r.returncode == 0 else (r.stderr or r.stdout or f"exit {r.returncode}")[:500]
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        out["probe_run"] = True
        out["probe_ok"] = False
        out["probe_error"] = str(e)[:500]
    return out


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
    manifest_limits: dict[str, Any] | None = None  # skill manifest.limits，合并入 policy
    policy_overrides: dict[str, Any] | None = None  # 仅请求层 overrides
    task_ref: TaskRefBody | None = None
    request_id: str | None = None  # 可选，用于幂等（与 Idempotency-Key 二选一）


def _artifacts_path_relative(project_id: str, exec_id: str) -> str:
    """相对 workspace_root 的路径，不暴露 host 绝对路径。"""
    return f"projects/{project_id}/artifacts/{exec_id}"


def _insert_running_record(
    db: Session,
    exec_id: str,
    project_id: str,
    task_id: str | None,
    conversation_id: str | None,
    skill_id: str | None,
    started_at: datetime,
    idempotency_key: str | None = None,
) -> None:
    """POST 进来立即插入 RUNNING，便于 UI 追踪与 crash 不丢记录。"""
    artifacts_path = _artifacts_path_relative(project_id, exec_id)
    rec = SandboxExecRecord(
        exec_id=exec_id,
        project_id=project_id,
        task_id=task_id,
        conversation_id=conversation_id,
        skill_id=skill_id,
        status=SandboxExecStatus.RUNNING,
        started_at=started_at,
        ended_at=None,
        duration_ms=None,
        artifacts_path=artifacts_path,
        idempotency_key=idempotency_key,
    )
    db.add(rec)
    db.commit()


def _update_exec_record(
    db: Session,
    exec_id: str,
    status: SandboxExecStatus,
    *,
    ended_at: datetime,
    image: str | None = None,
    command: str | None = None,
    args_json: str | None = None,
    cwd: str | None = None,
    env_keys_json: str | None = None,
    policy_snapshot: dict | None = None,
    exit_code: int | None = None,
    error_reason: dict | None = None,
    duration_ms: int | None = None,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
) -> None:
    """执行结束或异常后更新同一条记录。"""
    rec = db.query(SandboxExecRecord).filter(SandboxExecRecord.exec_id == exec_id).first()
    if not rec:
        return
    rec.status = status
    rec.ended_at = ended_at
    rec.duration_ms = duration_ms
    rec.stdout_truncated = stdout_truncated
    rec.stderr_truncated = stderr_truncated
    if image is not None:
        rec.image = image
    if command is not None:
        rec.cmd = command
    if args_json is not None:
        rec.args = args_json
    if cwd is not None:
        rec.cwd = cwd
    if env_keys_json is not None:
        rec.env_keys = env_keys_json
    if policy_snapshot is not None:
        rec.policy_snapshot = policy_snapshot
    if exit_code is not None:
        rec.exit_code = exit_code
    if error_reason is not None:
        rec.error_reason = json.dumps(error_reason, ensure_ascii=False)
    db.commit()


def _record_to_response(rec: SandboxExecRecord) -> dict:
    """
    从 DB 记录构造 POST 响应体（幂等复用）。
    POST 返回 exec_id、status（可能为 RUNNING 或最终态）；幂等命中或异步时 status=RUNNING，客户端可轮询 GET /execs/{id}。
    """
    return {
        "exec_id": rec.exec_id,
        "status": rec.status.value,
        "exit_code": rec.exit_code,
        "artifacts_dir": rec.artifacts_path or _artifacts_path_relative(rec.project_id, rec.exec_id),
        "stdout_path": "stdout.txt",
        "stderr_path": "stderr.txt",
        "stdout_truncated": rec.stdout_truncated,
        "stderr_truncated": rec.stderr_truncated,
        "error_reason": _parse_json(rec.error_reason),
    }


def execute_sandbox_body(body: SandboxExecBody, request: Request, db: Session) -> dict:
    """
    执行沙箱请求体（先插 RUNNING、再 run、再 update）。供 POST /sandbox/execs 与 POST /skills/{id}/invoke 复用。
    """
    idempotency_key = request.headers.get("Idempotency-Key") or body.request_id
    if idempotency_key and idempotency_key.strip():
        idempotency_key = idempotency_key.strip()
    else:
        idempotency_key = None

    settings = get_current_settings(db)
    exec_id = f"e_{uuid.uuid4().hex[:16]}"
    task_id = body.task_ref.task_id if body.task_ref else None
    conversation_id = body.task_ref.conversation_id if body.task_ref else None
    started_at = datetime.now(UTC)
    try:
        _insert_running_record(
            db, exec_id, body.project_id, task_id, conversation_id, body.skill_id,
            started_at, idempotency_key=idempotency_key,
        )
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            existing = db.query(SandboxExecRecord).filter(
                SandboxExecRecord.idempotency_key == idempotency_key,
            ).first()
            if existing:
                return _record_to_response(existing)
        raise


    req = SandboxExecRequest(
        project_id=body.project_id,
        skill_id=body.skill_id,
        exec_kind=body.exec.kind,
        command=body.exec.command,
        args=body.exec.args,
        cwd=body.exec.cwd or "work",
        env=body.exec.env,
        inputs=[SandboxExecInput(path=x.path, content=x.content) for x in body.inputs],
        manifest_limits=body.manifest_limits,
        policy_overrides=body.policy_overrides,
        task_id=task_id,
        conversation_id=conversation_id,
    )
    _env_keys_json = json.dumps(list((body.exec.env or {}).keys()), ensure_ascii=False)
    _args_json = json.dumps(body.exec.args, ensure_ascii=False)
    _cwd = body.exec.cwd or "work"

    try:
        resp = run_sandbox_exec(settings, req, exec_id=exec_id)
    except PolicyDeniedError as e:
        ended_at = datetime.now(UTC)
        _update_exec_record(
            db, exec_id, SandboxExecStatus.POLICY_DENIED,
            ended_at=ended_at,
            duration_ms=int((ended_at - started_at).total_seconds() * 1000),
            command=body.exec.command,
            args_json=_args_json,
            cwd=_cwd,
            env_keys_json=_env_keys_json,
            policy_snapshot=body.policy_overrides,
            error_reason=e.to_reason(),
        )
        raise HTTPException(status_code=403, detail=e.to_reason())
    except InvalidArgumentError as e:
        ended_at = datetime.now(UTC)
        _update_exec_record(
            db, exec_id, SandboxExecStatus.FAILED,
            ended_at=ended_at,
            duration_ms=int((ended_at - started_at).total_seconds() * 1000),
            command=body.exec.command,
            args_json=_args_json,
            cwd=_cwd,
            env_keys_json=_env_keys_json,
            policy_snapshot=body.policy_overrides,
            error_reason=e.to_reason(),
        )
        raise HTTPException(status_code=400, detail=e.to_reason())
    except SandboxRuntimeError as e:
        ended_at = datetime.now(UTC)
        _update_exec_record(
            db, exec_id, SandboxExecStatus.FAILED,
            ended_at=ended_at,
            duration_ms=int((ended_at - started_at).total_seconds() * 1000),
            command=body.exec.command,
            args_json=_args_json,
            cwd=_cwd,
            env_keys_json=_env_keys_json,
            policy_snapshot=body.policy_overrides,
            error_reason=e.to_reason(),
        )
        raise HTTPException(status_code=500, detail=e.to_reason())
    except Exception as e:
        # 其它未分类异常（如 ValueError 来自 path_adapter）统一返回 500 并带上真实信息，避免只返回 Internal Server Error
        reason = {"code": "RUNTIME_ERROR", "message": str(e)}
        ended_at = datetime.now(UTC)
        try:
            _update_exec_record(
                db, exec_id, SandboxExecStatus.FAILED,
                ended_at=ended_at,
                duration_ms=int((ended_at - started_at).total_seconds() * 1000),
                command=body.exec.command,
                args_json=_args_json,
                cwd=_cwd,
                env_keys_json=_env_keys_json,
                policy_snapshot=body.policy_overrides,
                error_reason=reason,
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=reason)

    ended_at = datetime.now(UTC)
    # 单一时间源：started_at/ended_at 均 UTC datetime，duration_ms 据此计算
    duration_ms = int((ended_at - started_at).total_seconds() * 1000)
    status_enum = SandboxExecStatus.SUCCEEDED if resp.status == "SUCCEEDED" else (
        SandboxExecStatus.TIMEOUT if resp.status == "TIMEOUT" else SandboxExecStatus.FAILED
    )
    _update_exec_record(
        db, exec_id, status_enum,
        ended_at=ended_at,
        duration_ms=duration_ms,
        image="lonelycat-sandbox:py312",
        command=body.exec.command,
        args_json=_args_json,
        cwd=_cwd,
        env_keys_json=_env_keys_json,
        policy_snapshot=body.policy_overrides,
        exit_code=resp.exit_code,
        error_reason=resp.error_reason,
        stdout_truncated=resp.stdout_truncated,
        stderr_truncated=resp.stderr_truncated,
    )
    rec = db.query(SandboxExecRecord).filter(SandboxExecRecord.exec_id == exec_id).first()
    return _record_to_response(rec)


@router.post("/execs", response_model=dict)
def post_sandbox_execs(
    request: Request,
    body: SandboxExecBody,
    db: Session = Depends(get_db),
) -> dict:
    """
    执行沙箱任务。policy 校验、normpath 防穿越、挂载仅三模板路径。
    审计：先插 RUNNING 再 update。幂等：Idempotency-Key 或 request_id，插入时写 key，并发重复则 IntegrityError 后查回已存在记录并返回（避免双执行）。
    响应：exec_id、status（RUNNING 或最终态），客户端可轮询 GET /execs/{id}。
    """
    return execute_sandbox_body(body, request, db)


@router.get("/execs", response_model=list)
def list_sandbox_execs(
    task_id: str | None = Query(None, description="按 task_id 筛选"),
    db: Session = Depends(get_db),
) -> list:
    """沙箱执行列表，支持 ?task_id=。按 started_at 倒序。"""
    q = db.query(SandboxExecRecord).order_by(SandboxExecRecord.started_at.desc())
    if task_id is not None:
        q = q.filter(SandboxExecRecord.task_id == task_id)
    rows = q.all()
    return [
        {
            "exec_id": r.exec_id,
            "project_id": r.project_id,
            "task_id": r.task_id,
            "conversation_id": r.conversation_id,
            "skill_id": r.skill_id,
            "status": r.status.value,
            "exit_code": r.exit_code,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "duration_ms": r.duration_ms,
            "artifacts_path": r.artifacts_path,
        }
        for r in rows
    ]


@router.get("/execs/{exec_id}", response_model=dict)
def get_sandbox_exec(exec_id: str, db: Session = Depends(get_db)) -> dict:
    """单条沙箱执行详情。"""
    rec = db.query(SandboxExecRecord).filter(SandboxExecRecord.exec_id == exec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="exec not found")
    return {
        "exec_id": rec.exec_id,
        "project_id": rec.project_id,
        "task_id": rec.task_id,
        "conversation_id": rec.conversation_id,
        "skill_id": rec.skill_id,
        "image": rec.image,
        "cmd": rec.cmd,
        "args": _parse_json(rec.args),
        "cwd": rec.cwd,
        "env_keys": _parse_json(rec.env_keys),
        "policy_snapshot": rec.policy_snapshot,
        "status": rec.status.value,
        "exit_code": rec.exit_code,
        "error_reason": _parse_json(rec.error_reason),
        "started_at": rec.started_at.isoformat() if rec.started_at else None,
        "ended_at": rec.ended_at.isoformat() if rec.ended_at else None,
        "duration_ms": rec.duration_ms,
        "artifacts_path": rec.artifacts_path,
        "stdout_truncated": rec.stdout_truncated,
        "stderr_truncated": rec.stderr_truncated,
    }


@router.get("/execs/{exec_id}/artifacts", response_model=dict)
def list_sandbox_exec_artifacts(exec_id: str, db: Session = Depends(get_db)) -> dict:
    """
    列出该次执行的产物文件（来自 manifest.json）。
    返回 exec_id、artifacts_dir（相对）、files、missing_manifest，便于 UI 区分 404/空/缺 manifest。
    """
    rec = db.query(SandboxExecRecord).filter(SandboxExecRecord.exec_id == exec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="exec not found")
    artifacts_dir = rec.artifacts_path  # 相对 workspace_root
    base = {"exec_id": exec_id, "artifacts_dir": artifacts_dir, "files": [], "missing_manifest": True, "missing_reason": None}
    if not rec.artifacts_path:
        base["missing_reason"] = "no_artifacts_path"
        return base
    settings = get_current_settings(db)
    try:
        adapter = HostPathAdapter(settings)
        root, _ = adapter.resolve_workspace_root()
    except Exception:
        raise HTTPException(status_code=500, detail="workspace config invalid")
    from pathlib import Path
    manifest_path = Path(root) / rec.artifacts_path / "manifest.json"
    if not manifest_path.is_file():
        base["missing_reason"] = "manifest_not_found"
        return base
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = data.get("files", [])
        return {"exec_id": exec_id, "artifacts_dir": artifacts_dir, "files": files, "missing_manifest": False, "missing_reason": None}
    except (json.JSONDecodeError, OSError):
        base["missing_reason"] = "read_error"
        return base
