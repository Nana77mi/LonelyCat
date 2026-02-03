import json

from agent_worker.chat_flow import chat_flow
from agent_worker.config import ChatConfig
from agent_worker.memory_gate import MEMORY_GATE_MARKER
from agent_worker.responder import FALLBACK_REPLY


class SwitchingLLM:
    def __init__(self, responder_text: str, gate_text: str) -> None:
        self.responder_text = responder_text
        self.gate_text = gate_text

    def generate(self, prompt: str) -> str:
        if MEMORY_GATE_MARKER in prompt:
            return self.gate_text
        return self.responder_text


class PersonaAwareLLM:
    def generate(self, prompt: str) -> str:
        if MEMORY_GATE_MARKER in prompt:
            return "NO_ACTION"
        if "You are LonelyCat" in prompt:
            return "Lonely reply."
        if "You are ProfessionalAssistant" in prompt:
            return "Professional reply."
        return "Default reply."


class MemorySpy:
    def __init__(self) -> None:
        self.list_calls = 0
        self.propose_calls = 0
        self.retract_calls = 0

    def list_facts(self, subject: str = "user", status: str = "ACTIVE"):
        self.list_calls += 1
        return []

    def propose(self, proposal, source_note: str = "mvp-1"):
        self.propose_calls += 1
        return "new-123"

    def retract(self, record_id: str, reason: str) -> None:
        self.retract_calls += 1


def test_persona_variation_memory_no_action():
    llm = PersonaAwareLLM()
    memory = MemorySpy()
    config = ChatConfig()

    result_lonely = chat_flow(
        user_message="Hi",
        persona_id="lonelycat",
        llm=llm,
        memory_client=memory,
        config=config,
    )
    result_prof = chat_flow(
        user_message="Hi",
        persona_id="professional",
        llm=llm,
        memory_client=memory,
        config=config,
    )

    assert result_lonely.assistant_reply != result_prof.assistant_reply
    assert result_lonely.memory_status == "NO_ACTION"
    assert result_prof.memory_status == "NO_ACTION"


def test_responder_bad_json_falls_back_to_raw_text():
    llm = SwitchingLLM("{bad json", "NO_ACTION")
    memory = MemorySpy()

    result = chat_flow(
        user_message="Hi",
        persona_id="lonelycat",
        llm=llm,
        memory_client=memory,
        config=ChatConfig(),
    )

    assert result.assistant_reply == "{bad json"
    assert result.memory_status == "NO_ACTION"


def test_gate_bad_json_returns_no_action():
    llm = SwitchingLLM("Sure thing.", "{bad json")
    memory = MemorySpy()

    result = chat_flow(
        user_message="Hi",
        persona_id="lonelycat",
        llm=llm,
        memory_client=memory,
        config=ChatConfig(),
    )

    assert result.memory_status == "NO_ACTION"


def test_gate_receives_responder_json_returns_no_action():
    responder_json = json.dumps({"assistant_reply": "hello", "memory": "NO_ACTION"})
    llm = SwitchingLLM("Sure thing.", responder_json)
    memory = MemorySpy()

    result = chat_flow(
        user_message="Hi",
        persona_id="lonelycat",
        llm=llm,
        memory_client=memory,
        config=ChatConfig(),
    )

    assert result.memory_status == "NO_ACTION"


def test_responder_receives_gate_json_falls_back():
    gate_json = json.dumps(
        {
            "action": "PROPOSE",
            "subject": "user",
            "predicate": "likes",
            "object": "cats",
            "confidence": 0.8,
        }
    )
    llm = SwitchingLLM(gate_json, "NO_ACTION")
    memory = MemorySpy()

    result = chat_flow(
        user_message="Hi",
        persona_id="lonelycat",
        llm=llm,
        memory_client=memory,
        config=ChatConfig(),
    )

    assert result.assistant_reply == FALLBACK_REPLY
    assert result.memory_status == "NO_ACTION"


def test_memory_disabled_skips_client_calls():
    llm = SwitchingLLM("Hello!", "NO_ACTION")
    memory = MemorySpy()
    config = ChatConfig(memory_enabled=False)

    result = chat_flow(
        user_message="Hi",
        persona_id="lonelycat",
        llm=llm,
        memory_client=memory,
        config=config,
    )

    assert result.memory_status == "NO_ACTION"
    assert memory.list_calls == 0
    assert memory.propose_calls == 0
    assert memory.retract_calls == 0


def test_chat_flow_trace_records_facts_snapshot_id_when_facts_provided():
    """Trace must record facts_snapshot_id (content hash, hex, predictable)."""
    import re
    from agent_worker.utils.facts_format import compute_facts_snapshot_id

    llm = SwitchingLLM("Okay.", "NO_ACTION")
    active_facts = [{"key": "likes", "value": "cats", "status": "active"}]

    result = chat_flow(
        user_message="Hi",
        persona_id="lonelycat",
        llm=llm,
        memory_client=None,
        config=ChatConfig(memory_enabled=False),
        active_facts=active_facts,
    )

    assert any("facts_snapshot_id" in line for line in result.trace_lines)
    snapshot_id = compute_facts_snapshot_id(active_facts)
    assert re.match(r"^[a-f0-9]{64}$", snapshot_id), "snapshot_id must be 64-char hex (content hash)"
    # BASIC level now includes facts_snapshot_id value in log (验收4)
    assert any(snapshot_id in line for line in result.trace_lines), "trace must contain snapshot_id value"
    assert snapshot_id == compute_facts_snapshot_id(active_facts)
