"""可选 integration：真实 docker run 冒烟。

层 1（人为开关）：仅当 RUN_DOCKER_IT=1 或 RUN_DOCKER_IT=diagnose 时才执行，否则 skip。
  - RUN_DOCKER_IT=1：严格门控，镜像必须可运行才跑，否则 skip 并给出原因。
  - RUN_DOCKER_IT=diagnose：镜像存在就跑，失败就失败（暴露 126 等真实错误）。

层 2（环境可用性）：启用后仍会 skip 的情况
  - docker version 不通 → skip
  - 镜像不存在 → skip
  - 镜像 OS/Arch 与 Engine 不一致 → skip 并提示 rebuild 命令
  - 最小探针 docker run ... -lc 'true' 失败 → skip（stderr 截断进 skip reason）

用法：RUN_DOCKER_IT=1 pytest -m integration 或 pytest -m sandbox_it
"""
from __future__ import annotations

import os
import subprocess

import pytest

from app.services.sandbox.schemas import SandboxExecRequest

IMAGE = "lonelycat-sandbox:py312"


def _run_docker_it() -> bool:
    """层 1：是否启用 integration（默认不跑）。"""
    return os.environ.get("RUN_DOCKER_IT") in ("1", "diagnose")


def _diagnose_mode() -> bool:
    """是否为诊断模式：镜像存在就跑，不要求可运行。"""
    return os.environ.get("RUN_DOCKER_IT") == "diagnose"


def _docker_available() -> bool:
    try:
        r = subprocess.run(["docker", "version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _sandbox_image_exists() -> bool:
    """镜像是否在本地存在（docker image inspect）。"""
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", IMAGE],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _get_engine_platform() -> tuple[str | None, str | None]:
    """(Os, Arch) 或 (None, None)。"""
    try:
        r = subprocess.run(
            ["docker", "info", "--format", "{{.OSType}} {{.Architecture}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return (None, None)
        parts = r.stdout.strip().split()
        return (parts[0] if len(parts) > 0 else None, parts[1] if len(parts) > 1 else None)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (None, None)


def _get_image_platform() -> tuple[str | None, str | None]:
    """(Os, Architecture) 或 (None, None)。"""
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", IMAGE, "--format", "{{.Os}} {{.Architecture}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return (None, None)
        parts = r.stdout.strip().split()
        return (parts[0] if len(parts) > 0 else None, parts[1] if len(parts) > 1 else None)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (None, None)


def _sandbox_image_runnable() -> tuple[bool, str]:
    """最小探针：docker run --rm --entrypoint bash IMAGE -lc 'true'。返回 (成功, 失败原因)。"""
    try:
        r = subprocess.run(
            [
                "docker", "run", "--rm",
                "--entrypoint", "bash",
                IMAGE,
                "-lc", "true",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode == 0:
            return (True, "")
        err = (r.stderr or r.stdout or "").strip()
        err_short = "\n".join(err.splitlines()[:5]) if err else "(no stderr)"
        e_os, e_arch = _get_engine_platform()
        i_os, i_arch = _get_image_platform()
        reason = f"image exists but not runnable (exit {r.returncode}): {err_short}"
        if e_os is not None and i_os is not None and (e_os != i_os or e_arch != i_arch):
            plat = f"{e_os}/{e_arch}"
            reason += f". Engine {e_os}/{e_arch} vs image {i_os}/{i_arch}. Rebuild: docker buildx build --platform {plat} -t {IMAGE} -f docker/sandbox/Dockerfile ."
        return (False, reason)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return (False, f"probe failed: {e}")


def _integration_skip_reason() -> str | None:
    """层 1 + 层 2 检查。返回 None 表示可以跑，否则返回 skip 原因。diagnose 模式下不因 runnable 失败而 skip。"""
    if not _run_docker_it():
        return "integration disabled (set RUN_DOCKER_IT=1 or RUN_DOCKER_IT=diagnose to run)"
    if not _docker_available():
        return "docker not available"
    if not _sandbox_image_exists():
        return f"{IMAGE} image not found (run scripts/build_sandbox_image.ps1 or build_sandbox_image.sh)"
    if _diagnose_mode():
        return None  # 诊断模式：存在就跑，不检查 runnable
    ok, reason = _sandbox_image_runnable()
    if not ok:
        return reason
    return None


def _integration_settings(tmp_path):
    """返回使用 tmp_path 作为 workspace 的 settings（Windows 用同一路径）。"""
    root = str(tmp_path)
    return {
        "sandbox": {
            "workspace_root_win": root,
            "workspace_root_wsl": root,
            "runtime_mode": "windows",
        }
    }


@pytest.mark.integration
@pytest.mark.sandbox_it
class TestSandboxIntegrationDocker:
    """真实 docker run 冒烟：bash -lc \"echo hello\"、python -c \"print(123)\"。"""

    @pytest.fixture
    def workspace_root(self, tmp_path):
        return tmp_path

    def test_shell_echo_hello(self, workspace_root):
        skip = _integration_skip_reason()
        if skip:
            pytest.skip(skip)
        from app.services.sandbox.runner_docker import run_sandbox_exec

        settings = _integration_settings(workspace_root)
        req = SandboxExecRequest(
            project_id="p1",
            skill_id="shell.run",
            exec_kind="shell",
            command="bash",
            args=["-lc", "echo hello"],
        )
        resp = run_sandbox_exec(settings, req)
        assert resp.status == "SUCCEEDED"
        assert resp.exit_code == 0
        assert resp.artifacts_dir.startswith("projects/")
        assert resp.stdout_path == "stdout.txt"
        stdout_full = os.path.join(workspace_root, resp.artifacts_dir, resp.stdout_path)
        assert os.path.isfile(stdout_full)
        assert b"hello" in open(stdout_full, "rb").read()

    def test_python_print_123(self, workspace_root):
        skip = _integration_skip_reason()
        if skip:
            pytest.skip(skip)
        from app.services.sandbox.runner_docker import run_sandbox_exec

        settings = _integration_settings(workspace_root)
        req = SandboxExecRequest(
            project_id="p1",
            skill_id="python.run",
            exec_kind="python",
            command="python",
            args=["-c", "print(123)"],
        )
        resp = run_sandbox_exec(settings, req)
        assert resp.status == "SUCCEEDED"
        assert resp.exit_code == 0
        stdout_full = os.path.join(workspace_root, resp.artifacts_dir, resp.stdout_path)
        assert os.path.isfile(stdout_full)
        assert b"123" in open(stdout_full, "rb").read()


@pytest.mark.integration
@pytest.mark.sandbox_it
class TestSandboxIntegrationTimeout:
    """sleep 999 + timeout_ms=1000 → status=TIMEOUT。"""

    def test_timeout_returns_timeout_status(self, tmp_path):
        skip = _integration_skip_reason()
        if skip:
            pytest.skip(skip)
        from app.services.sandbox.runner_docker import run_sandbox_exec

        settings = _integration_settings(tmp_path)
        req = SandboxExecRequest(
            project_id="p1",
            skill_id="shell.run",
            exec_kind="shell",
            command="bash",
            args=["-lc", "sleep 999"],
            policy_overrides={"timeout_ms": 1000},
        )
        resp = run_sandbox_exec(settings, req)
        assert resp.status == "TIMEOUT"
        assert resp.error_reason is not None
        assert resp.error_reason.get("code") == "TIMEOUT"


@pytest.mark.integration
@pytest.mark.sandbox_it
class TestSandboxIntegrationTruncation:
    """生成 >1MB 输出 → stdout_truncated=True。"""

    def test_stdout_truncated_when_over_limit(self, tmp_path):
        skip = _integration_skip_reason()
        if skip:
            pytest.skip(skip)
        from app.services.sandbox.runner_docker import run_sandbox_exec

        settings = _integration_settings(tmp_path)
        req = SandboxExecRequest(
            project_id="p1",
            skill_id="shell.run",
            exec_kind="shell",
            command="bash",
            args=["-lc", "python3 -c \"print('x' * 1600000)\""],
            policy_overrides={"max_stdout_bytes": 1024 * 1024},
        )
        resp = run_sandbox_exec(settings, req)
        assert resp.stdout_truncated is True
        stdout_full = os.path.join(tmp_path, resp.artifacts_dir, resp.stdout_path)
        assert os.path.isfile(stdout_full)
        size = os.path.getsize(stdout_full)
        assert size <= 1024 * 1024 + 4096  # 接近 1MB
