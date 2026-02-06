"""PR2/PR2.5: Sandbox runner、API 与 health 测试。"""
from __future__ import annotations

import pytest

from app.services.sandbox.errors import InvalidArgumentError, PolicyDeniedError
from app.services.sandbox.runner_docker import (
    _validate_exec_kind_command,
    _validate_input_path,
    run_sandbox_exec,
)
from app.services.sandbox.schemas import SandboxExecInput, SandboxExecRequest


class TestValidateInputPath:
    """inputs[].path normpath 拒绝 ../。"""

    def test_reject_path_traversal(self):
        with pytest.raises(InvalidArgumentError, match="禁止路径穿越"):
            _validate_input_path("../hack.txt")
        with pytest.raises(InvalidArgumentError, match="禁止路径穿越"):
            _validate_input_path("a/../../b.txt")
        with pytest.raises(InvalidArgumentError, match="禁止路径穿越"):
            _validate_input_path("/etc/passwd")  # 绝对路径

    def test_accept_relative_inputs_path(self):
        assert _validate_input_path("input.txt") == "input.txt"
        assert _validate_input_path("a/b.txt") == "a/b.txt"
        assert _validate_input_path("a/b/c") == "a/b/c"


class TestValidateExecKindCommand:
    """exec.kind=shell → command=bash, args [-lc, script]; kind=python → command=python, args [-c, ...]。"""

    def test_shell_ok(self):
        _validate_exec_kind_command(
            SandboxExecRequest(
                project_id="p1",
                skill_id="shell.run",
                exec_kind="shell",
                command="bash",
                args=["-lc", "echo 1"],
            )
        )

    def test_shell_wrong_command(self):
        with pytest.raises(PolicyDeniedError, match="command 必须为 bash"):
            _validate_exec_kind_command(
                SandboxExecRequest(
                    project_id="p1",
                    skill_id=None,
                    exec_kind="shell",
                    command="sh",
                    args=["-lc", "echo 1"],
                )
            )

    def test_shell_wrong_args(self):
        with pytest.raises(PolicyDeniedError, match="args 须形如"):
            _validate_exec_kind_command(
                SandboxExecRequest(
                    project_id="p1",
                    skill_id=None,
                    exec_kind="shell",
                    command="bash",
                    args=["echo", "1"],
                )
            )

    def test_python_ok_c(self):
        _validate_exec_kind_command(
            SandboxExecRequest(
                project_id="p1",
                skill_id="python.run",
                exec_kind="python",
                command="python",
                args=["-c", "print(1)"],
            )
        )

    def test_python_ok_script(self):
        _validate_exec_kind_command(
            SandboxExecRequest(
                project_id="p1",
                skill_id="python.run",
                exec_kind="python",
                command="python",
                args=["/workspace/inputs/main.py"],
            )
        )

    def test_python_wrong_command(self):
        with pytest.raises(PolicyDeniedError, match="command 必须为 python"):
            _validate_exec_kind_command(
                SandboxExecRequest(
                    project_id="p1",
                    skill_id=None,
                    exec_kind="python",
                    command="python3",
                    args=["-c", "print(1)"],
                )
            )

    def test_invalid_kind(self):
        with pytest.raises(PolicyDeniedError, match="shell 或 python"):
            _validate_exec_kind_command(
                SandboxExecRequest(
                    project_id="p1",
                    skill_id=None,
                    exec_kind="node",
                    command="node",
                    args=["-e", "1"],
                )
            )


class TestRunSandboxExecPathTraversal:
    """run_sandbox_exec 对 inputs path 穿越返回/抛出。"""

    def test_path_traversal_raises(self):
        settings = {
            "sandbox": {
                "workspace_root_win": "D:\\Project\\lonelycat\\workspace",
                "workspace_root_wsl": "/mnt/d/Project/lonelycat/workspace",
                "runtime_mode": "windows",
            }
        }
        req = SandboxExecRequest(
            project_id="p1",
            skill_id="shell.run",
            exec_kind="shell",
            command="bash",
            args=["-lc", "echo 1"],
            inputs=[SandboxExecInput(path="../hack.txt", content="x")],
        )
        with pytest.raises(InvalidArgumentError, match="禁止路径穿越"):
            run_sandbox_exec(settings, req)


class TestSandboxHealth:
    """GET /sandbox/health 返回 runtime_mode、workspace_root_native、workspace_root_docker_mount、docker_*、platform、writable_check。"""

    def test_get_sandbox_health_returns_expected_keys(self):
        from app.services.sandbox.docker_health import get_sandbox_health
        settings = {"sandbox": {"workspace_root_win": "", "workspace_root_wsl": "", "runtime_mode": "windows"}}
        out = get_sandbox_health(settings)
        assert "runtime_mode" in out
        assert "workspace_root_native" in out
        assert "workspace_root_docker_mount" in out
        assert "docker_cli_path" in out
        assert "docker_version" in out
        assert "docker_context" in out
        assert "docker_info" in out
        assert "platform" in out
        assert "writable_check" in out
        assert "ok" in out["writable_check"]
        assert out["runtime_mode"] in ("windows", "wsl")
        assert out["docker_cli_path"] == "docker"
        assert "os" in out["platform"] and "release" in out["platform"] and "is_wsl" in out["platform"]
        # 只断言字段存在与类型、受控失败值，不断言具体内容（不同 Docker 版本差异大）
        for key in ("docker_version", "docker_context", "docker_info"):
            assert key in out
            assert isinstance(out[key], str)
            if out[key] in ("(not found)", "(error)"):
                continue  # 受控失败值
            assert len(out[key]) > 0  # 成功时应有内容

    def test_get_sandbox_health_with_workspace_writable(self):
        from app.services.sandbox.docker_health import get_sandbox_health
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp(prefix="lc_sandbox_health_")
        try:
            settings = {
                "sandbox": {
                    "workspace_root_win": tmp,
                    "workspace_root_wsl": tmp,
                    "runtime_mode": "windows",
                }
            }
            out = get_sandbox_health(settings)
            assert out["writable_check"]["ok"] is True
            assert out["workspace_root_native"] == tmp
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
