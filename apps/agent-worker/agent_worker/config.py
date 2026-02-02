from __future__ import annotations

import os
from dataclasses import dataclass


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"0", "false", "off", "no"}:
        return False
    if normalized in {"1", "true", "on", "yes"}:
        return True
    return default


@dataclass(frozen=True)
class ChatConfig:
    memory_enabled: bool = True
    memory_allow_update: bool = True
    memory_allow_retract: bool = True
    persona_default: str = "lonelycat"

    @classmethod
    def from_env(cls) -> "ChatConfig":
        return cls(
            memory_enabled=_read_bool_env("MEMORY_ENABLED", True),
            memory_allow_update=_read_bool_env("MEMORY_ALLOW_UPDATE", True),
            memory_allow_retract=_read_bool_env("MEMORY_ALLOW_RETRACT", True),
            persona_default=os.getenv("PERSONA_DEFAULT", "lonelycat"),
        )
