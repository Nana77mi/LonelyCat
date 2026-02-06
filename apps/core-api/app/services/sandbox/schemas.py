"""Sandbox policy and request/response schemas (PR0/PR2). See docs/spec/sandbox.md."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SandboxPolicy:
    """系统默认 policy（系统级）。合并规则：系统默认 ← Settings ← Skill manifest ← 请求 overrides。"""
    net_mode: str = "none"
    timeout_ms: int = 60_000
    max_stdout_bytes: int = 1_048_576  # 1MB
    max_stderr_bytes: int = 1_048_576  # 1MB
    max_artifacts_bytes_total: int = 52_428_800  # 50MB
    memory_mb: int = 1024
    cpu_cores: float = 1.0
    pids: int = 256
    max_concurrent_execs: int = 4


@dataclass
class SandboxExecInput:
    """单条 input：path 相对 inputs/，写入前 normpath 校验拒绝 ../。"""
    path: str
    content: str | bytes


@dataclass
class SandboxExecRequest:
    """POST /sandbox/execs 请求体（内部用）。"""
    project_id: str
    skill_id: str | None
    exec_kind: str  # shell | python
    command: str
    args: list[str]
    cwd: str = "work"
    env: dict[str, str] | None = None
    inputs: list[SandboxExecInput] = field(default_factory=list)
    policy_overrides: dict[str, Any] | None = None
    task_id: str | None = None
    conversation_id: str | None = None


@dataclass
class SandboxExecResponse:
    """POST /sandbox/execs 返回。artifacts_dir/stdout_path/stderr_path 为相对路径。"""
    exec_id: str
    status: str  # SUCCEEDED | FAILED | TIMEOUT | POLICY_DENIED
    exit_code: int | None
    artifacts_dir: str  # 相对 workspace 根，如 projects/p1/artifacts/e_xxx
    stdout_path: str    # 相对 artifacts_dir，固定 stdout.txt
    stderr_path: str    # 相对 artifacts_dir，固定 stderr.txt
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    error_reason: dict | None = None  # {"code": "POLICY_DENIED"|"INVALID_ARGUMENT"|"RUNTIME_ERROR"|"TIMEOUT", "message": "..."}
