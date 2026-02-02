import json

import agent_worker.chat as chat
from agent_worker.fact_agent import FactProposal
from agent_worker.memory_gate import MEMORY_GATE_MARKER, MemoryGate
from agent_worker.persona import PersonaRegistry
from agent_worker.responder import POLICY_PROMPT, Responder
from agent_worker.router import NoActionDecision


class RecordingFakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class PersonaAwareLLM:
    def __init__(self) -> None:
        self.prompts = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "You are LonelyCat" in prompt:
            return "Lonely reply."
        if "You are ProfessionalAssistant" in prompt:
            return "Professional reply."
        if MEMORY_GATE_MARKER in prompt:
            return "NO_ACTION"
        return "Default reply."


class GateActionFakeLLM:
    def generate(self, prompt: str) -> str:
        if MEMORY_GATE_MARKER in prompt:
            return json.dumps(
                {
                    "action": "PROPOSE",
                    "subject": "user",
                    "predicate": "likes",
                    "object": "cats",
                    "confidence": 0.9,
                }
            )
        return "Sure thing."


class MemorySpy:
    def __init__(self, facts=None) -> None:
        self.facts = facts or []
        self.propose_calls = []
        self.list_calls = []
        self.retract_calls = []
        self.response_id = "new-123"

    def list_facts(self, subject: str = "user", status: str = "ACTIVE"):
        self.list_calls.append({"subject": subject, "status": status})
        return self.facts

    def propose(self, proposal: FactProposal, source_note: str = "mvp-1"):
        self.propose_calls.append({"proposal": proposal, "source_note": source_note})
        return self.response_id

    def retract(self, record_id: str, reason: str) -> None:
        self.retract_calls.append({"record_id": record_id, "reason": reason})


def test_responder_prompt_includes_persona_policy():
    llm = RecordingFakeLLM("Hello.")
    responder = Responder(llm)
    persona = PersonaRegistry.load_default().get("lonelycat")

    reply, memory_hint = responder.reply(persona, "Hi", [])

    assert reply
    assert memory_hint == "NO_ACTION"
    assert llm.prompts
    prompt = llm.prompts[0]
    assert persona.system_prompt in prompt
    assert POLICY_PROMPT in prompt


def test_gate_prompt_excludes_persona():
    llm = RecordingFakeLLM("NO_ACTION")
    gate = MemoryGate(llm)

    decision = gate.decide("Hello", [])

    assert isinstance(decision, NoActionDecision)
    prompt = llm.prompts[0]
    assert "You are LonelyCat" not in prompt
    assert "You are ProfessionalAssistant" not in prompt
    assert MEMORY_GATE_MARKER in prompt


def test_chat_persona_hot_swap_no_action():
    llm = PersonaAwareLLM()
    memory = MemorySpy()

    reply_lonely, status_lonely = chat.chat(
        "Hi", persona_id="lonelycat", llm=llm, memory_client=memory
    )
    reply_professional, status_professional = chat.chat(
        "Hi", persona_id="professional", llm=llm, memory_client=memory
    )

    assert reply_lonely != reply_professional
    assert status_lonely == "NO_ACTION"
    assert status_professional == "NO_ACTION"


def test_chat_two_stage_flow_propose_called():
    llm = GateActionFakeLLM()
    memory = MemorySpy()

    reply, status = chat.chat(
        "I like cats", persona_id="lonelycat", llm=llm, memory_client=memory
    )

    assert isinstance(reply, str) and reply
    assert memory.propose_calls
    assert "PROPOSE" in status
