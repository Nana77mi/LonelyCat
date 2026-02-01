from protocol.events import InboundEvent, OutboundMessage
from protocol.mcp import MCPServerManifest
from protocol.memory import FactCandidate, FactRecord
from protocol.skills import SkillManifest
from protocol.tools import ToolCall, ToolResult


def test_protocol_models_can_instantiate():
    inbound = InboundEvent(source="test", payload={"hello": "world"})
    outbound = OutboundMessage(target="test", content="hi")
    tool_call = ToolCall(name="example", arguments={"a": 1})
    tool_result = ToolResult(name="example", output={"ok": True})
    skill = SkillManifest(name="skill", version="0.1.0")
    mcp = MCPServerManifest(name="mcp", version="0.1.0")
    candidate = FactCandidate(content="fact", confidence=0.5)
    record = FactRecord(content="fact", source="test")

    assert inbound.source == "test"
    assert outbound.target == "test"
    assert tool_call.name == "example"
    assert tool_result.output == {"ok": True}
    assert skill.name == "skill"
    assert mcp.name == "mcp"
    assert candidate.content == "fact"
    assert record.source == "test"
