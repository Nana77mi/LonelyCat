import json

from agent_worker.cli import main
from agent_worker.fact_agent import FactGate


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def decide(self, text: str) -> str:
        return self.response


class MemorySpy:
    def __init__(self) -> None:
        self.calls = []
        self.response_id = "record-123"

    def propose(self, candidate, source_note: str = "mvp-1"):
        self.calls.append({"proposal": candidate, "source_note": source_note})
        return self.response_id


def test_cli_no_fact(capsys):
    llm = FakeLLM("NO_FACT")

    class NoCallMemory:
        def propose(self, candidate, source_note: str = "mvp-1"):
            raise AssertionError("Memory client should not be called")

    main(["It is raining today"], llm=llm, memory_client=NoCallMemory())
    captured = capsys.readouterr()
    assert captured.out.strip() == "NO_FACT"


def test_cli_proposes_fact(capsys):
    payload = {
        "subject": "user",
        "predicate": "likes",
        "object": "cats",
        "confidence": 0.9,
    }
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy()

    main(["I like cats"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.calls
    assert "PROPOSED" in captured.out
    assert "subject=user" in captured.out
    assert "predicate=likes" in captured.out
    assert "object=cats" in captured.out


def test_gate_parses_code_fence():
    payload = {
        "subject": "user",
        "predicate": "likes",
        "object": "tea",
        "confidence": 0.7,
    }
    response = """```json\n{\n  \"subject\": \"user\",\n  \"predicate\": \"likes\",\n  \"object\": \"tea\",\n  \"confidence\": 0.7\n}\n```"""
    gate = FactGate(FakeLLM(response))

    candidate = gate.decide("I like tea")

    assert candidate is not None
    assert candidate.subject == payload["subject"]
    assert candidate.predicate == payload["predicate"]
    assert candidate.object == payload["object"]
    assert candidate.confidence == payload["confidence"]


def test_gate_rejects_invalid_json():
    gate = FactGate(FakeLLM("```json not-json```"))

    assert gate.decide("bad") is None
