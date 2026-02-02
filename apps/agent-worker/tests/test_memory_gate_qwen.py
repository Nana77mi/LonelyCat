import json

from agent_worker.llm.base import BaseLLM
from agent_worker.memory_gate import MemoryGate
from agent_worker.router import NoActionDecision, ProposeDecision, RetractDecision


class FakeLLM(BaseLLM):
    def __init__(self, response: str) -> None:
        super().__init__()
        self._response = response

    def generate(self, prompt: str) -> str:
        return self._response


def test_gate_parses_fenced_json_with_extra_text():
    payload = {
        "action": "PROPOSE",
        "subject": "user",
        "predicate": "likes",
        "object": "cats",
        "confidence": 0.9,
    }
    response = (
        "Sure! Here is the result:\n"
        "```json\n"
        f"{json.dumps(payload)}\n"
        "```\n"
        "Thanks!"
    )
    llm = FakeLLM(response)
    gate = MemoryGate(llm)

    decision = gate.decide("I really love cats. Please remember this.", [])

    assert isinstance(decision, ProposeDecision)
    assert decision.predicate == "likes"
    assert decision.object == "cats"


def test_gate_proposes_preference():
    payload = {
        "action": "PROPOSE",
        "subject": "user",
        "predicate": "likes",
        "object": "cats",
        "confidence": 0.91,
    }
    llm = FakeLLM(json.dumps(payload))
    gate = MemoryGate(llm)

    decision = gate.decide("I really love cats. Please remember this.", [])

    assert isinstance(decision, ProposeDecision)
    assert decision.confidence == payload["confidence"]


def test_gate_retracts_preference_when_fact_exists():
    payload = {
        "action": "RETRACT",
        "subject": "user",
        "predicate": "likes",
        "object": "cats",
        "reason": "no longer true",
    }
    llm = FakeLLM(json.dumps(payload))
    gate = MemoryGate(llm)
    active_facts = [{"predicate": "likes", "object": "cats", "id": "fact-1"}]

    decision = gate.decide("I don't like cats anymore.", active_facts)

    assert isinstance(decision, RetractDecision)


def test_gate_sensitive_info_returns_no_action():
    llm = FakeLLM("NO_ACTION")
    gate = MemoryGate(llm)

    decision = gate.decide("My phone number is 123-456-7890, remember it", [])

    assert isinstance(decision, NoActionDecision)
