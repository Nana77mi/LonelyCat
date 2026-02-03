from protocol.events import InboundEvent, OutboundMessage
from protocol.mcp import MCPServerManifest
from protocol.memory import FactCandidate, FactRecord
from protocol.run_constants import TRACE_ID_PATTERN, is_valid_trace_id
from protocol.skills import SkillManifest
from protocol.tools import ToolCall, ToolResult


def schema_for(model: type) -> dict:
    """Lightweight JSON schema helper."""
    return model.model_json_schema()


__all__ = [
    "FactCandidate",
    "FactRecord",
    "InboundEvent",
    "MCPServerManifest",
    "OutboundMessage",
    "SkillManifest",
    "ToolCall",
    "ToolResult",
    "TRACE_ID_PATTERN",
    "is_valid_trace_id",
    "schema_for",
]
