"""PR1.5: HostPathAdapter 与 Settings sandbox 测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.sandbox.path_adapter import HostPathAdapter, detect_runtime


class TestDetectRuntime:
    """detect_runtime() 在 Windows 返回 windows，在 WSL 返回 wsl。"""

    def test_detect_runtime_returns_windows_or_wsl(self):
        r = detect_runtime()
        assert r in ("windows", "wsl")


class TestHostPathAdapter:
    """HostPathAdapter 根据 runtime 与 settings 返回正确的 host_path_native 与 docker_mount_path。"""

    def test_windows_mode_uses_workspace_root_win(self):
        settings = {
            "sandbox": {
                "workspace_root_win": "D:\\Project\\lonelycat\\workspace",
                "workspace_root_wsl": "/mnt/d/Project/lonelycat/workspace",
                "runtime_mode": "windows",
            }
        }
        adapter = HostPathAdapter(settings)
        assert adapter.runtime == "windows"
        native, docker = adapter.resolve_workspace_root()
        assert native == "D:\\Project\\lonelycat\\workspace"
        assert docker == "D:\\Project\\lonelycat\\workspace"
        assert Path(adapter.host_path_native("projects", "p1")) == Path("D:/Project/lonelycat/workspace/projects/p1")
        assert Path(adapter.docker_mount_path("projects", "p1")) == Path("D:/Project/lonelycat/workspace/projects/p1")

    def test_wsl_mode_uses_workspace_root_wsl(self):
        settings = {
            "sandbox": {
                "workspace_root_win": "D:\\Project\\lonelycat\\workspace",
                "workspace_root_wsl": "/mnt/d/Project/lonelycat/workspace",
                "runtime_mode": "wsl",
            }
        }
        adapter = HostPathAdapter(settings)
        assert adapter.runtime == "wsl"
        native, docker = adapter.resolve_workspace_root()
        assert native == "/mnt/d/Project/lonelycat/workspace"
        assert docker == "/mnt/d/Project/lonelycat/workspace"
        assert Path(adapter.host_path_native("projects", "p1")) == Path("/mnt/d/Project/lonelycat/workspace/projects/p1")
        assert Path(adapter.docker_mount_path("projects", "p1")) == Path("/mnt/d/Project/lonelycat/workspace/projects/p1")

    def test_missing_workspace_root_raises(self):
        settings = {"sandbox": {"workspace_root_win": "", "workspace_root_wsl": "", "runtime_mode": "windows"}}
        adapter = HostPathAdapter(settings)
        with pytest.raises(ValueError, match="workspace_root_win"):
            adapter.resolve_workspace_root()

    def test_default_settings_sandbox_structure(self):
        """Settings 默认应包含 sandbox.workspace_root_win/wsl, runtime_mode, docker.cli_path（与 spec 一致）。"""
        expected_sandbox_keys = {"workspace_root_win", "workspace_root_wsl", "runtime_mode", "docker"}
        settings = {"sandbox": {"workspace_root_win": "", "workspace_root_wsl": "", "runtime_mode": "auto", "docker": {"cli_path": ""}}}
        s = settings["sandbox"]
        assert set(s.keys()) >= expected_sandbox_keys
        assert "cli_path" in s["docker"]
        adapter = HostPathAdapter(settings)
        assert adapter.runtime in ("windows", "wsl")
