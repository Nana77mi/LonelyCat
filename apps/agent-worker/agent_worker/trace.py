from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from enum import Enum


class TraceLevel(Enum):
    OFF = "off"
    BASIC = "1"
    FULL = "full"


@dataclass(frozen=True)
class TraceEvent:
    stage: str
    detail: str | None = None


class TraceCollector:
    def __init__(self, level: TraceLevel, trace_id: str | None = None) -> None:
        self.level = level
        self.trace_id = trace_id or uuid.uuid4().hex
        self.events: list[TraceEvent] = []

    @classmethod
    def from_env(cls) -> "TraceCollector":
        raw = os.getenv("LONELYCAT_TRACE")
        if raw is None:
            level = TraceLevel.BASIC
        else:
            normalized = raw.strip().lower()
            if normalized in {"off", "0", "false", "none"}:
                level = TraceLevel.OFF
            elif normalized in {"full", "2"}:
                level = TraceLevel.FULL
            else:
                level = TraceLevel.BASIC
        return cls(level=level)

    def record(self, stage: str, detail: str | None = None) -> None:
        self.events.append(TraceEvent(stage=stage, detail=detail))

    def render_lines(self) -> list[str]:
        if self.level is TraceLevel.OFF:
            return []
        lines = []
        for event in self.events:
            if self.level is TraceLevel.BASIC:
                lines.append(f"trace_id={self.trace_id} stage={event.stage}")
            else:
                detail = _truncate(_sanitize(event.detail or ""))
                lines.append(
                    f"trace_id={self.trace_id} stage={event.stage} detail={detail}"
                )
        return lines


_KEY_PATTERN = re.compile(r"(OPENAI_API_KEY\s*[:=]\s*)([^\s\"']+)", re.IGNORECASE)


def _sanitize(text: str) -> str:
    if not text:
        return ""
    return _KEY_PATTERN.sub(r"\1***", text)


def _truncate(text: str, limit: int = 500) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...(truncated)"
