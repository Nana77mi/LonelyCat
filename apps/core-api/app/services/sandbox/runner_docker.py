"""Docker runner for sandbox exec (PR2). Policy 校验、normpath、三模板挂载、流式截断、manifest/meta。见 docs/spec/sandbox.md。"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import uuid
from pathlib import Path

from app.services.sandbox.errors import InvalidArgumentError, PolicyDeniedError, SandboxRuntimeError
from app.services.sandbox.path_adapter import HostPathAdapter
from app.services.sandbox.schemas import (
    SandboxExecInput,
    SandboxExecRequest,
    SandboxExecResponse,
    SandboxPolicy,
)

# 系统默认 policy
_DEFAULT_POLICY = SandboxPolicy()

# 并发 semaphore（按 max_concurrent_execs 限制）
_semaphore: threading.Semaphore | None = None
_semaphore_limit: int = 0


def _get_semaphore(limit: int) -> threading.Semaphore:
    global _semaphore, _semaphore_limit
    if _semaphore is None or _semaphore_limit != limit:
        _semaphore = threading.Semaphore(max(1, limit))
        _semaphore_limit = limit
    return _semaphore


def _policy_from_settings(settings: dict) -> SandboxPolicy:
    """从 settings 合并 sandbox 相关到 SandboxPolicy。settings 为 hard-cap（上限），请求 overrides 只能更严。"""
    p = SandboxPolicy(
        timeout_ms=_DEFAULT_POLICY.timeout_ms,
        max_stdout_bytes=_DEFAULT_POLICY.max_stdout_bytes,
        max_stderr_bytes=_DEFAULT_POLICY.max_stderr_bytes,
        max_artifacts_bytes_total=_DEFAULT_POLICY.max_artifacts_bytes_total,
        memory_mb=_DEFAULT_POLICY.memory_mb,
        cpu_cores=_DEFAULT_POLICY.cpu_cores,
        pids=_DEFAULT_POLICY.pids,
        max_concurrent_execs=_DEFAULT_POLICY.max_concurrent_execs,
    )
    sandbox = settings.get("sandbox") or {}
    limits = sandbox.get("limits") or {}
    if isinstance(limits.get("timeout_ms"), (int, float)) and limits["timeout_ms"] >= 1000:
        p.timeout_ms = min(int(limits["timeout_ms"]), 300_000)
    if isinstance(limits.get("max_stdout_bytes"), (int, float)) and limits["max_stdout_bytes"] >= 0:
        p.max_stdout_bytes = min(int(limits["max_stdout_bytes"]), 10 * 1024 * 1024)
    if isinstance(limits.get("max_stderr_bytes"), (int, float)) and limits["max_stderr_bytes"] >= 0:
        p.max_stderr_bytes = min(int(limits["max_stderr_bytes"]), 10 * 1024 * 1024)
    if isinstance(limits.get("max_artifacts_bytes_total"), (int, float)) and limits["max_artifacts_bytes_total"] >= 0:
        p.max_artifacts_bytes_total = min(int(limits["max_artifacts_bytes_total"]), 200 * 1024 * 1024)
    if isinstance(limits.get("memory_mb"), (int, float)) and limits["memory_mb"] >= 1:
        p.memory_mb = min(int(limits["memory_mb"]), 4096)
    if isinstance(limits.get("cpu_cores"), (int, float)) and limits["cpu_cores"] >= 0.1:
        p.cpu_cores = min(float(limits["cpu_cores"]), 4.0)
    if isinstance(limits.get("pids"), (int, float)) and limits["pids"] >= 1:
        p.pids = min(int(limits["pids"]), 512)
    if isinstance(sandbox.get("max_concurrent_execs"), (int, float)) and sandbox["max_concurrent_execs"] >= 1:
        p.max_concurrent_execs = min(int(sandbox["max_concurrent_execs"]), 16)
    return p


def _merge_manifest_limits(base: SandboxPolicy, limits: dict | None) -> SandboxPolicy:
    """合并 skill manifest limits；base 为 hard-cap，limits 只能更严格。"""
    if not limits:
        return base
    p = SandboxPolicy(
        net_mode=base.net_mode,
        timeout_ms=base.timeout_ms,
        max_stdout_bytes=base.max_stdout_bytes,
        max_stderr_bytes=base.max_stderr_bytes,
        max_artifacts_bytes_total=base.max_artifacts_bytes_total,
        memory_mb=base.memory_mb,
        cpu_cores=base.cpu_cores,
        pids=base.pids,
        max_concurrent_execs=base.max_concurrent_execs,
    )
    if isinstance(limits.get("timeout_ms"), (int, float)) and 1000 <= limits["timeout_ms"] <= base.timeout_ms:
        p.timeout_ms = int(limits["timeout_ms"])
    if isinstance(limits.get("memory_mb"), (int, float)) and 1 <= limits["memory_mb"] <= base.memory_mb:
        p.memory_mb = int(limits["memory_mb"])
    if isinstance(limits.get("cpu_cores"), (int, float)) and 0.1 <= limits["cpu_cores"] <= base.cpu_cores:
        p.cpu_cores = float(limits["cpu_cores"])
    if isinstance(limits.get("pids"), (int, float)) and 1 <= limits["pids"] <= base.pids:
        p.pids = int(limits["pids"])
    if isinstance(limits.get("max_stdout_bytes"), (int, float)) and 0 <= limits["max_stdout_bytes"] <= base.max_stdout_bytes:
        p.max_stdout_bytes = int(limits["max_stdout_bytes"])
    if isinstance(limits.get("max_stderr_bytes"), (int, float)) and 0 <= limits["max_stderr_bytes"] <= base.max_stderr_bytes:
        p.max_stderr_bytes = int(limits["max_stderr_bytes"])
    if isinstance(limits.get("max_artifacts_bytes_total"), (int, float)) and 0 <= limits["max_artifacts_bytes_total"] <= base.max_artifacts_bytes_total:
        p.max_artifacts_bytes_total = int(limits["max_artifacts_bytes_total"])
    return p


def _merge_policy_overrides(base: SandboxPolicy, overrides: dict | None) -> SandboxPolicy:
    """合并请求 overrides；base 为 hard-cap，overrides 只能更严格（更小 timeout/内存等）。"""
    if not overrides:
        return base
    p = SandboxPolicy(
        net_mode=base.net_mode,
        timeout_ms=base.timeout_ms,
        max_stdout_bytes=base.max_stdout_bytes,
        max_stderr_bytes=base.max_stderr_bytes,
        max_artifacts_bytes_total=base.max_artifacts_bytes_total,
        memory_mb=base.memory_mb,
        cpu_cores=base.cpu_cores,
        pids=base.pids,
        max_concurrent_execs=base.max_concurrent_execs,
    )
    if isinstance(overrides.get("timeout_ms"), (int, float)) and 1000 <= overrides["timeout_ms"] <= base.timeout_ms:
        p.timeout_ms = int(overrides["timeout_ms"])
    if isinstance(overrides.get("memory_mb"), (int, float)) and 1 <= overrides["memory_mb"] <= base.memory_mb:
        p.memory_mb = int(overrides["memory_mb"])
    if isinstance(overrides.get("cpu_cores"), (int, float)) and 0.1 <= overrides["cpu_cores"] <= base.cpu_cores:
        p.cpu_cores = float(overrides["cpu_cores"])
    return p


def _validate_exec_kind_command(req: SandboxExecRequest) -> None:
    """Phase 1：kind=shell → command=bash, args [-lc, script]; kind=python → command=python, args [-c, code] or [path]。"""
    if req.exec_kind == "shell":
        if req.command != "bash":
            raise PolicyDeniedError("exec.kind=shell 时 command 必须为 bash")
        if len(req.args) < 2 or req.args[0] != "-lc":
            raise PolicyDeniedError("exec.kind=shell 时 args 须形如 [\"-lc\", \"<script>\"]")
    elif req.exec_kind == "python":
        if req.command != "python":
            raise PolicyDeniedError("exec.kind=python 时 command 必须为 python")
        if not req.args or (req.args[0] not in ("-c", "-u") and not req.args[0].startswith("/workspace/inputs/")):
            raise PolicyDeniedError("exec.kind=python 时 args 须形如 [\"-c\", \"<code>\"] 或 [\"/workspace/inputs/...\"]")
    else:
        raise PolicyDeniedError("exec.kind 须为 shell 或 python")


def _validate_input_path(path: str) -> str:
    """inputs[].path 只允许相对 inputs/，normpath 拒绝 ../ 与绝对路径。返回规范化相对路径。"""
    p = path.replace("\\", "/").strip()
    if not p:
        raise InvalidArgumentError("inputs[].path 不能为空")
    if p.startswith("/") or os.path.isabs(path):
        raise InvalidArgumentError(f"inputs[].path 禁止路径穿越: {path}")
    p = p.lstrip("/")
    normalized = os.path.normpath(p).replace("\\", "/")
    if ".." in normalized or normalized.startswith("/"):
        raise InvalidArgumentError(f"inputs[].path 禁止路径穿越: {path}")
    return normalized


def _stream_read_to_file(
    stream: object,
    path: Path,
    max_bytes: int,
) -> tuple[int, bool]:
    """从 stream 读取并写入文件，超过 max_bytes 后仅 drain 不再写。返回 (写入字节数, 是否截断)。"""
    written = 0
    truncated = False
    if stream is None or not hasattr(stream, "read"):
        return (0, False)
    with open(path, "wb") as f:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            if written < max_bytes:
                to_write = chunk[: max_bytes - written]
                f.write(to_write)
                written += len(to_write)
                if len(chunk) > len(to_write):
                    truncated = True
            else:
                truncated = True
    return (written, truncated)


def _run_docker_streaming(
    cmd: list[str],
    timeout_sec: int,
    stdout_path: Path,
    stderr_path: Path,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
) -> tuple[int | None, str, bytes, bytes, bool, bool]:
    """
    流式执行 docker，分别读 stdout/stderr 写文件并截断，避免 PIPE 死锁与全量内存。
    返回 (exit_code, status, out_bytes, err_bytes, stdout_truncated, stderr_truncated)。
    status 为 SUCCEEDED | FAILED | TIMEOUT。
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out_truncated = False
    err_truncated = False
    out_done = threading.Event()
    err_done = threading.Event()
    out_result: list[tuple[int, bool]] = []
    err_result: list[tuple[int, bool]] = []

    def read_stdout():
        try:
            if proc.stdout:
                n, tr = _stream_read_to_file(proc.stdout, stdout_path, max_stdout_bytes)
                out_result.append((n, tr))
        finally:
            out_done.set()

    def read_stderr():
        try:
            if proc.stderr:
                n, tr = _stream_read_to_file(proc.stderr, stderr_path, max_stderr_bytes)
                err_result.append((n, tr))
        finally:
            err_done.set()

    t_out = threading.Thread(target=read_stdout)
    t_err = threading.Thread(target=read_stderr)
    t_out.start()
    t_err.start()
    try:
        proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        t_out.join(timeout=5)
        t_err.join(timeout=5)
        out_bytes = (stdout_path.read_bytes() if stdout_path.exists() else b"")[:max_stdout_bytes]
        err_bytes = (stderr_path.read_bytes() if stderr_path.exists() else b"")[:max_stderr_bytes]
        return (None, "TIMEOUT", out_bytes, err_bytes, len(out_bytes) >= max_stdout_bytes, len(err_bytes) >= max_stderr_bytes)
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    out_truncated = out_result[0][1] if out_result else False
    err_truncated = err_result[0][1] if err_result else False
    out_bytes = stdout_path.read_bytes() if stdout_path.exists() else b""
    err_bytes = stderr_path.read_bytes() if stderr_path.exists() else b""
    return (proc.returncode or 0, "SUCCEEDED" if proc.returncode == 0 else "FAILED", out_bytes, err_bytes, out_truncated, err_truncated)


def run_sandbox_exec(settings: dict, req: SandboxExecRequest, exec_id: str | None = None) -> SandboxExecResponse:
    """
    执行沙箱任务：policy 校验、准备目录、写 inputs、docker run、截断写 stdout/stderr、生成 manifest/meta。
    挂载仅限 workspace/projects/<project_id>/{inputs,work,artifacts} 三模板路径。
    exec_id 可选，由 API 传入时用于审计记录对齐。
    """
    # Policy
    base_policy = _policy_from_settings(settings)
    if req.manifest_limits:
        base_policy = _merge_manifest_limits(base_policy, req.manifest_limits)
    policy = _merge_policy_overrides(base_policy, req.policy_overrides)
    _validate_exec_kind_command(req)

    # Inputs path 校验
    for inp in req.inputs:
        _validate_input_path(inp.path)

    try:
        adapter = HostPathAdapter(settings)
    except Exception as e:
        raise SandboxRuntimeError(f"workspace 配置无效: {e}")

    exec_id = exec_id or f"e_{uuid.uuid4().hex[:16]}"
    project_id = req.project_id

    # 仅使用三模板路径
    inputs_host = adapter.host_path_native("projects", project_id, "inputs")
    work_host = adapter.host_path_native("projects", project_id, "work")
    artifacts_host = adapter.host_path_native("projects", project_id, "artifacts", exec_id)
    inputs_docker = adapter.docker_mount_path("projects", project_id, "inputs")
    work_docker = adapter.docker_mount_path("projects", project_id, "work")
    artifacts_docker = adapter.docker_mount_path("projects", project_id, "artifacts", exec_id)

    try:
        os.makedirs(inputs_host, exist_ok=True)
        os.makedirs(work_host, exist_ok=True)
        os.makedirs(artifacts_host, exist_ok=True)
    except OSError as e:
        raise SandboxRuntimeError(f"创建目录失败: {e}")

    for inp in req.inputs:
        rel = _validate_input_path(inp.path)
        out_path = Path(inputs_host) / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        content = inp.content
        if isinstance(content, str):
            content = content.encode("utf-8")
        try:
            out_path.write_bytes(content)
        except OSError as e:
            raise SandboxRuntimeError(f"写入 input 失败: {e}")

    docker_mounts = [
        f"{inputs_docker}:/workspace/inputs:ro",
        f"{work_docker}:/workspace/work:rw",
        f"{artifacts_docker}:/workspace/artifacts:rw",
    ]
    cli = (settings.get("sandbox") or {}).get("docker") or {}
    docker_cmd = (cli.get("cli_path") or "").strip() or "docker"
    image = "lonelycat-sandbox:py312"
    timeout_sec = max(1, policy.timeout_ms // 1000)

    container_name = f"lonelycat-sbx-{exec_id[:8]}"
    cmd = [
        docker_cmd, "run", "--rm",
        "--network=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user=1000:1000",
        "--workdir=/workspace/work",
        f"--name={container_name}",
        f"--memory={policy.memory_mb}m",
        f"--cpus={policy.cpu_cores}",
        f"--pids-limit={policy.pids}",
    ]
    for m in docker_mounts:
        cmd.extend(["-v", m])
    for k, v in (req.env or {}).items():
        cmd.extend(["-e", f"{k}={v}"])
    cmd.append(image)
    cmd.extend([req.command] + req.args)

    stdout_path = Path(artifacts_host) / "stdout.txt"
    stderr_path = Path(artifacts_host) / "stderr.txt"
    sem = _get_semaphore(policy.max_concurrent_execs)
    with sem:
        exit_code, status, out_bytes, err_bytes, stdout_truncated, stderr_truncated = _run_docker_streaming(
            cmd,
            timeout_sec,
            stdout_path,
            stderr_path,
            policy.max_stdout_bytes,
            policy.max_stderr_bytes,
        )
    if status == "TIMEOUT":
        # 超时后 subprocess kill 可能未通知 docker 清理，强制 rm 避免残留容器
        try:
            subprocess.run(
                [docker_cmd, "rm", "-f", container_name],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass
        error_reason = {"code": "TIMEOUT", "message": f"执行超时（{timeout_sec}s）"}
    else:
        error_reason = None

    # manifest.json: 仅统计 artifacts/<exec_id>/ 下文件；path 统一为相对 artifacts_dir 的文件名（便于 UI/S3 迁移）
    manifest_entries = []
    art_path = Path(artifacts_host)
    for f in art_path.iterdir():
        if f.is_file():
            data = f.read_bytes()
            manifest_entries.append({
                "path": f.name,  # 相对 artifacts_dir，如 stdout.txt、stderr.txt、meta.json
                "size": len(data),
                "hash": hashlib.sha256(data).hexdigest(),
            })
    (Path(artifacts_host) / "manifest.json").write_text(
        json.dumps({"files": manifest_entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    artifacts_dir_relative = f"projects/{project_id}/artifacts/{exec_id}"
    meta = {
        "exec_id": exec_id,
        "project_id": project_id,
        "status": status,
        "exit_code": exit_code,
        "policy_snapshot": {
            "timeout_ms": policy.timeout_ms,
            "max_stdout_bytes": policy.max_stdout_bytes,
            "max_stderr_bytes": policy.max_stderr_bytes,
        },
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "docker_mounts": docker_mounts,
        "docker_image": image,
        "docker_args": cmd,
    }
    (Path(artifacts_host) / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return SandboxExecResponse(
        exec_id=exec_id,
        status=status,
        exit_code=exit_code,
        artifacts_dir=artifacts_dir_relative,
        stdout_path="stdout.txt",
        stderr_path="stderr.txt",
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        error_reason=error_reason,
    )
