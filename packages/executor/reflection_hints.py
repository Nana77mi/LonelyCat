"""
Reflection Hints - Phase 2.4-C

Schema and I/O for reflection-derived hints used by WriteGate/Planner.
Hints influence only explanation/suggestion text, NOT verdict (deterministic).
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class ReflectionHints:
    """
    Standardized reflection output for injection into WriteGate/Planner.

    - hot_error_steps: step names that fail often (e.g. ["verify", "health"])
    - false_allow_patterns: patterns that were allowed but led to failure
    - slow_steps: step names with high average duration
    - suggested_policy: free-form suggestions (e.g. "Consider adding verification for X")
    """
    hot_error_steps: List[str] = field(default_factory=list)
    false_allow_patterns: List[str] = field(default_factory=list)
    slow_steps: List[str] = field(default_factory=list)
    suggested_policy: List[str] = field(default_factory=list)
    evidence_execution_ids: List[str] = field(default_factory=list)  # exec_ids used to generate
    window: Optional[str] = None  # e.g. "7d"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReflectionHints":
        return cls(
            hot_error_steps=data.get("hot_error_steps", []),
            false_allow_patterns=data.get("false_allow_patterns", []),
            slow_steps=data.get("slow_steps", []),
            suggested_policy=data.get("suggested_policy", []),
            evidence_execution_ids=data.get("evidence_execution_ids", []),
            window=data.get("window"),
        )

    def digest(self) -> str:
        """SHA256 digest of canonical JSON for audit."""
        canonical = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def to_suggestion_strings(self) -> List[str]:
        """Human-readable strings for WriteGate reasons (explanation only)."""
        out = []
        if self.hot_error_steps:
            out.append(f"Recent failures often at step(s): {', '.join(self.hot_error_steps)}.")
        if self.slow_steps:
            out.append(f"Slower steps historically: {', '.join(self.slow_steps)}.")
        for s in self.suggested_policy[:3]:  # Limit to 3
            out.append(s)
        return out


def load_hints(path: Path) -> Optional[ReflectionHints]:
    """Load reflection hints from JSON file. Returns None if file missing or invalid."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ReflectionHints.from_dict(data)
    except Exception:
        return None


def save_hints(path: Path, hints: ReflectionHints) -> None:
    """Save reflection hints to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hints.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
