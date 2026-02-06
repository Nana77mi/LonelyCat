"""HostPathAdapter: Win/WSL 双栈路径，供 docker run -v 使用。见 docs/spec/sandbox.md。"""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Literal, Tuple

RuntimeMode = Literal["auto", "windows", "wsl"]


def detect_runtime() -> Literal["windows", "wsl"]:
    """检测当前运行环境：Windows 或 WSL（Linux 且含 Microsoft）。"""
    if os.name == "nt":
        return "windows"
    # Linux: 检查是否 WSL（/proc/version 或 platform.release() 含 microsoft）
    try:
        with open("/proc/version", encoding="utf-8", errors="replace") as f:
            if "microsoft" in f.read().lower():
                return "wsl"
    except OSError:
        pass
    if "microsoft" in (platform.release() or "").lower():
        return "wsl"
    # 非 WSL 的 Linux 视为 wsl 路径风格（/ 路径），Docker 通常也在 Linux 上跑
    return "wsl"


def _wslpath_to_win(wsl_path: str) -> str | None:
    """WSL 路径转 Windows 路径。当 core-api 跑在 Windows 时通过 wsl wslpath -w 调用。"""
    try:
        r = subprocess.run(
            ["wsl", "wslpath", "-w", wsl_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _win_to_wslpath(win_path: str) -> str | None:
    """Windows 路径转 WSL 路径。需在 WSL 内执行 wslpath -u。"""
    try:
        r = subprocess.run(
            ["wslpath", "-u", win_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


class HostPathAdapter:
    """
    同一 workspace 根在 Windows/WSL 下的路径转换。
    - host_path_native: 当前系统可读写的绝对路径（写文件、listdir 用）
    - docker_mount_path: 传给 docker run -v 的 host 侧路径（Windows 用 D:\\...，WSL 用 /mnt/d/...）
    """

    def __init__(self, settings: dict) -> None:
        sandbox = settings.get("sandbox") or {}
        self._workspace_root_win = (sandbox.get("workspace_root_win") or "").strip()
        self._workspace_root_wsl = (sandbox.get("workspace_root_wsl") or "").strip()
        mode = (sandbox.get("runtime_mode") or "auto").strip().lower()
        if mode not in ("auto", "windows", "wsl"):
            mode = "auto"
        self._runtime_mode: RuntimeMode = mode  # type: ignore[assignment]
        self._runtime: Literal["windows", "wsl"] = (
            detect_runtime() if self._runtime_mode == "auto" else self._runtime_mode  # type: ignore[assignment]
        )

    @property
    def runtime(self) -> Literal["windows", "wsl"]:
        """当前生效的运行环境。"""
        return self._runtime

    def resolve_workspace_root(self) -> Tuple[str, str]:
        """
        返回 (host_path_native, docker_mount_path)。
        host_path_native: 当前系统下 workspace 根的绝对路径（用于创建目录、写文件）。
        docker_mount_path: 传给 docker run -v 的路径（本机形态：Windows 用 D:\\...，WSL 用 /mnt/d/...）。
        若缺少配置且 wslpath 转换失败，抛出 ValueError。
        """
        if self._runtime == "windows":
            native = self._workspace_root_win
            if not native and self._workspace_root_wsl:
                native = _wslpath_to_win(self._workspace_root_wsl)
            if not native:
                raise ValueError(
                    "sandbox.workspace_root_win 未配置，且无法从 workspace_root_wsl 通过 wslpath -w 转换。"
                    "请设置 Settings 中 sandbox.workspace_root_win（如 D:\\Project\\lonelycat\\workspace）。"
                )
            # Windows 下 Docker Desktop 使用 Windows 路径
            docker_path = native
        else:
            native = self._workspace_root_wsl
            if not native and self._workspace_root_win:
                native = _win_to_wslpath(self._workspace_root_win)
            if not native:
                raise ValueError(
                    "sandbox.workspace_root_wsl 未配置，且无法从 workspace_root_win 通过 wslpath -u 转换。"
                    "请设置 Settings 中 sandbox.workspace_root_wsl（如 /mnt/d/Project/lonelycat/workspace）。"
                )
            docker_path = native
        return (native, docker_path)

    def host_path_native(self, *parts: str) -> str:
        """当前系统下 workspace 内某相对路径的绝对路径（用于读写文件）。"""
        root, _ = self.resolve_workspace_root()
        return str(Path(root).joinpath(*parts))

    def docker_mount_path(self, *parts: str) -> str:
        """传给 docker run -v 的 host 侧绝对路径。"""
        _, docker_root = self.resolve_workspace_root()
        return str(Path(docker_root).joinpath(*parts))
