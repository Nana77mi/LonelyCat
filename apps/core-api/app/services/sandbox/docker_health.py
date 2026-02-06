"""Docker 健康检查：将 docker context show 与 docker info 摘要写入日志。见 docs/spec/sandbox.md PR1.5。"""
from __future__ import annotations

import subprocess


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
