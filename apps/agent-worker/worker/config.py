from __future__ import annotations

import os

# Worker 配置参数
RUN_LEASE_SECONDS = int(os.getenv("RUN_LEASE_SECONDS", "60"))
RUN_HEARTBEAT_SECONDS = int(os.getenv("RUN_HEARTBEAT_SECONDS", "20"))
RUN_POLL_SECONDS = int(os.getenv("RUN_POLL_SECONDS", "1"))
RUN_MAX_ATTEMPTS = int(os.getenv("RUN_MAX_ATTEMPTS", "3"))
