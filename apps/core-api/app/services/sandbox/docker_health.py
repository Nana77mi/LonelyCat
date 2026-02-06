"""Docker 健康检查：日志输出与 GET /sandbox/health 结构化返回。见 docs/spec/sandbox.md PR1.5/PR2.5。"""
from __future__ import annotations

import os
import platform as plat
import subprocess
import tempfile
from typing import Any


def log_docker_context_and_info(cli_path: str = "docker") -> None:
    """执行 docker context show 与 docker info，将输出摘要写入日志（便于 Win/WSL 联调）。"""
    for name, args in [("context", [cli_path, "context", "show"]), ("info", [cli_path, "info"])]:
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=10)
            out = (r.stdout or "").strip() or (r.stderr or "").strip()
            if out:
                lines = out.splitlines()[:20]
                summary = "\n  ".join(lines)
                print(f"[sandbox] docker {name}:\n  {summary}")
            elif r.returncode != 0:
                print(f"[sandbox] docker {name} failed (exit {r.returncode})")
        except FileNotFoundError:
            print(f"[sandbox] docker {name}: cli not found ({cli_path})")
        except subprocess.TimeoutExpired:
            print(f"[sandbox] docker {name}: timeout")


def _run_capture(cli_path: str, args: list[str], timeout: int = 10) -> tuple[str | None, int | None]:
    """执行命令，返回 (stdout 前 30 行, returncode)。异常时返回 (None, None)。"""
    try:
        r = subprocess.run(
            [cli_path] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        lines = out.splitlines()[:30]
        return ("\n".join(lines), r.returncode)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (None, None)


def get_sandbox_health(settings: dict) -> dict[str, Any]:
    """
    返回 GET /sandbox/health 结构化数据：runtime_mode、workspace_root_native、
    workspace_root_docker_mount、docker_cli_path、docker_version、docker_context、
    docker_info、platform、writable_check。
    """
    sandbox = settings.get("sandbox") or {}
    cli_path = (sandbox.get("docker") or {}).get("cli_path") or ""
    cli_path = (cli_path or "docker").strip() or "docker"

    adapter = None
    runtime_mode = "unknown"
    workspace_root_native = ""
    workspace_root_docker_mount = ""
    writable_ok: bool | None = None
    writable_error: str | None = None

    try:
        from app.services.sandbox.path_adapter import HostPathAdapter
        adapter = HostPathAdapter(settings)
        runtime_mode = adapter.runtime
        workspace_root_native, workspace_root_docker_mount = adapter.resolve_workspace_root()
        # 可写检查：在 workspace 下尝试创建临时文件
        test_dir = os.path.join(workspace_root_native, "projects", "_health_check")
        os.makedirs(test_dir, exist_ok=True)
        fd, path = tempfile.mkstemp(dir=test_dir, prefix=".", suffix=".tmp")
        os.close(fd)
        os.remove(path)
        os.rmdir(test_dir)
        writable_ok = True
    except Exception as e:
        writable_error = str(e)
        if adapter is not None:
            runtime_mode = adapter.runtime
            try:
                workspace_root_native, workspace_root_docker_mount = adapter.resolve_workspace_root()
            except Exception:
                pass

    docker_version_out, docker_version_code = _run_capture(cli_path, ["version"])
    docker_context_out, docker_context_code = _run_capture(cli_path, ["context", "show"])
    docker_info_out, _ = _run_capture(cli_path, ["info"])

    platform_info: dict[str, Any] = {
        "os": plat.system(),
        "release": plat.release(),
        "is_wsl": runtime_mode == "wsl",
    }
    writable_check: dict[str, Any] = {"ok": True} if writable_error is None else {"ok": False, "error": writable_error}
    return {
        "runtime_mode": runtime_mode,
        "workspace_root_native": workspace_root_native,
        "workspace_root_docker_mount": workspace_root_docker_mount,
        "docker_cli_path": cli_path,
        "docker_version": docker_version_out if docker_version_out else ("(not found)" if docker_version_code is None else "(error)"),
        "docker_context": docker_context_out if docker_context_out else ("(not found)" if docker_context_code is None else "(error)"),
        "docker_info": docker_info_out if (docker_info_out and docker_info_out.strip()) else ("(not found)" if docker_info_out is None else "(error)"),
        "platform": platform_info,
        "writable_check": writable_check,
    }
