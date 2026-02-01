from protocol.events import InboundEvent, OutboundMessage
from protocol.mcp import MCPServerManifest
from protocol.memory import FactCandidate, FactRecord
from protocol.skills import SkillManifest
from protocol.tools import ToolCall, ToolResult


def schema_for(model: type) -> dict:
    """Lightweight JSON schema helper."""
    return model.model_json_schema()


__all__ = [
    "InboundEvent",
    "OutboundMessage",
    "ToolCall",
    "ToolResult",
    "SkillManifest",
    "MCPServerManifest",
    "FactCandidate",
    "FactRecord",
    "schema_for",
]
