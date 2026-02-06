"""Sandbox policy and request/response schemas (PR0). See docs/spec/sandbox.md."""
from __future__ import annotations

from dataclasses import dataclass, field


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
