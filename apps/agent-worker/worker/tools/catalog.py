"""ToolMeta v0 and ToolCatalog: name, input_schema, side_effects, risk_level, provider_id."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolMeta:
    """Tool metadata for catalog and policy (side_effects / risk_level for WAIT_CONFIRM)."""

    name: str
    input_schema: Dict[str, Any]  # JSON Schema or minimal dict
    side_effects: bool = False
    risk_level: str = "read_only"  # read_only | write
    budget: Optional[Dict[str, Any]] = None
    provider_id: str = "builtin"


class ToolCatalog:
    """Registry of tool metadata; builtin tools registered at module load."""

    def __init__(self) -> None:
        self._by_name: Dict[str, ToolMeta] = {}

    def register(self, meta: ToolMeta) -> None:
        self._by_name[meta.name] = meta

    def get(self, name: str) -> Optional[ToolMeta]:
        return self._by_name.get(name)

    def unregister(self, name: str) -> None:
        """Remove tool from catalog (e.g. for tests: simulate missing tool)."""
        self._by_name.pop(name, None)

    def list_builtin(self) -> List[ToolMeta]:
        return list(self._by_name.values())


def _builtin_tool_meta() -> List[ToolMeta]:
    return [
        ToolMeta(
            name="web.search",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            side_effects=False,
            risk_level="read_only",
            provider_id="builtin",
        ),
        ToolMeta(
            name="web.fetch",
            input_schema={
                "type": "object",
                "properties": {"urls": {"type": "array", "items": {"type": "string"}}},
                "required": ["urls"],
            },
            side_effects=False,
            risk_level="read_only",
            provider_id="builtin",
        ),
        ToolMeta(
            name="text.summarize",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}, "max_length": {"type": "integer"}},
                "required": ["text"],
            },
            side_effects=False,
            risk_level="read_only",
            provider_id="builtin",
        ),
    ]


# Singleton catalog with builtin tools
_default_catalog: Optional[ToolCatalog] = None


def get_default_catalog() -> ToolCatalog:
    global _default_catalog
    if _default_catalog is None:
        _default_catalog = ToolCatalog()
        for meta in _builtin_tool_meta():
            _default_catalog.register(meta)
    return _default_catalog
