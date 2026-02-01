import json

from agent_worker.retract_agent import RetractGate
from agent_worker.retract_cli import main


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def decide(self, text: str) -> str:
        return self.response


class MemorySpy:
    def __init__(self, facts=None) -> None:
        self.facts = facts or []
        self.list_calls = []
        self.retract_calls = []

    def list_facts(self, subject="user", status="ACTIVE"):
        self.list_calls.append({"subject": subject, "status": status})
        return self.facts

    def retract(self, record_id: str, reason: str) -> None:
        self.retract_calls.append({"record_id": record_id, "reason": reason})


def test_cli_no_action(capsys):
    llm = FakeLLM("NO_ACTION")

    class NoCallMemory:
        def list_facts(self, subject="user", status="ACTIVE"):
            raise AssertionError("list_facts should not be called")

        def retract(self, record_id: str, reason: str) -> None:
            raise AssertionError("retract should not be called")

    main(["I no longer like cats"], llm=llm, memory_client=NoCallMemory())
    captured = capsys.readouterr()
    assert captured.out.strip() == "NO_ACTION"


def test_cli_retracts_fact(capsys):
    payload = {
        "action": "RETRACT",
        "subject": "user",
        "predicate": "likes",
        "object": "cats",
        "reason": "user corrected preference",
    }
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy(
        facts=[
            {
                "id": "record-1",
                "subject": "user",
                "predicate": "likes",
                "object": "cats",
                "status": "ACTIVE",
            }
        ]
    )

    main(["I do not like cats anymore"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.list_calls
    assert memory.retract_calls == [
        {"record_id": "record-1", "reason": payload["reason"]}
    ]
    assert "RETRACTED" in captured.out
    assert "record-1" in captured.out


def test_cli_retract_not_found(capsys):
    payload = {
        "action": "RETRACT",
        "subject": "user",
        "predicate": "likes",
        "object": "cats",
        "reason": "user corrected preference",
    }
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy(facts=[])

    main(["I do not like cats anymore"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.list_calls
    assert not memory.retract_calls
    assert "NOT_FOUND" in captured.out


def test_gate_parses_code_fence():
    response = """```json\n{\n  \"action\": \"RETRACT\",\n  \"subject\": \"user\",\n  \"predicate\": \"likes\",\n  \"object\": \"tea\",\n  \"reason\": \"user corrected preference\"\n}\n```"""
    gate = RetractGate(FakeLLM(response))

    request = gate.decide("I do not like tea")

    assert request is not None
    assert request.subject == "user"
    assert request.predicate == "likes"
    assert request.object == "tea"
    assert request.reason == "user corrected preference"


def test_gate_rejects_invalid_json():
    gate = RetractGate(FakeLLM("```json not-json```"))

    assert gate.decide("bad") is None
