import json

from agent_worker.update_agent import UpdateGate
from agent_worker.update_cli import main


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
        self.propose_calls = []

    def list_facts(self, scope="global", status="active", **kwargs):
        self.list_calls.append({"scope": scope, "status": status, **kwargs})
        return self.facts

    def revoke(self, record_id: str) -> None:
        self.retract_calls.append({"record_id": record_id})

    def propose(self, proposal, source_note: str = "mvp-1") -> str:
        self.propose_calls.append({"proposal": proposal, "source_note": source_note})
        return "new-123"


def test_cli_no_action(capsys):
    llm = FakeLLM("NO_ACTION")

    class NoCallMemory:
        def list_facts(self, scope="global", status="active", **kwargs):
            raise AssertionError("list_facts should not be called")

        def revoke(self, record_id: str) -> None:
            raise AssertionError("revoke should not be called")

        def propose(self, proposal, source_note: str = "mvp-1") -> str:
            raise AssertionError("propose should not be called")

    main(["I like cats more than dogs"], llm=llm, memory_client=NoCallMemory())
    captured = capsys.readouterr()
    assert captured.out.strip() == "NO_ACTION"


def test_cli_update_success(capsys):
    payload = {
        "action": "UPDATE",
        "subject": "user",
        "predicate": "likes",
        "old_object": "cats",
        "new_object": "dogs",
        "confidence": 0.8,
        "reason": "user preference changed",
    }
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy(
        facts=[
            {
                "id": "old-1",
                "subject": "user",
                "predicate": "likes",
                "object": "cats",
                "status": "ACTIVE",
            }
        ]
    )

    main(["I like dogs more than cats"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.list_calls
    assert memory.retract_calls == [
        {"record_id": "old-1", "reason": payload["reason"]}
    ]
    assert memory.propose_calls
    propose_call = memory.propose_calls[0]
    assert propose_call["proposal"].object == payload["new_object"]
    assert propose_call["proposal"].confidence == payload["confidence"]
    assert propose_call["source_note"] == "update"
    assert "UPDATED" in captured.out
    assert "old-1" in captured.out
    assert "new-123" in captured.out


def test_cli_update_not_found(capsys):
    payload = {
        "action": "UPDATE",
        "subject": "user",
        "predicate": "likes",
        "old_object": "cats",
        "new_object": "dogs",
        "confidence": 0.8,
        "reason": "user preference changed",
    }
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy(facts=[])

    main(["I like dogs more than cats"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.list_calls
    assert not memory.retract_calls
    assert not memory.propose_calls
    assert "NOT_FOUND_OLD" in captured.out


def test_gate_parses_code_fence():
    response = (
        "```json\n{\n"
        '  "action": "UPDATE",\n'
        '  "subject": "user",\n'
        '  "predicate": "likes",\n'
        '  "old_object": "cats",\n'
        '  "new_object": "dogs",\n'
        '  "confidence": 0.4,\n'
        '  "reason": "user preference changed"\n'
        "}\n```"
    )
    gate = UpdateGate(FakeLLM(response))

    request = gate.decide("I like dogs more than cats")

    assert request is not None
    assert request.subject == "user"
    assert request.predicate == "likes"
    assert request.old_object == "cats"
    assert request.new_object == "dogs"
    assert request.confidence == 0.4
    assert request.reason == "user preference changed"


def test_gate_rejects_invalid_json():
    gate = UpdateGate(FakeLLM("```json not-json```"))

    assert gate.decide("bad") is None
