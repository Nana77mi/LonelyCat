import json

from agent_worker.run import execute_decision, main
from agent_worker.router import parse_llm_output, ProposeDecision, RetractDecision, UpdateDecision
from agent_worker.trace import TraceCollector, TraceLevel


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate(self, prompt: str) -> str:
        return self.response


class MemorySpy:
    def __init__(self, facts=None) -> None:
        self.facts = facts or []
        self.propose_calls = []
        self.list_calls = []
        self.retract_calls = []
        self.response_id = "new-123"

    def list_facts(self, scope="global", status="active", **kwargs):
        self.list_calls.append({"scope": scope, "status": status, **kwargs})
        return self.facts

    def propose(self, proposal, source_note: str = "mvp-1"):
        self.propose_calls.append({"proposal": proposal, "source_note": source_note})
        return self.response_id

    def revoke(self, record_id: str) -> None:
        self.retract_calls.append({"record_id": record_id})


def test_run_no_action(capsys):
    llm = FakeLLM("NO_ACTION")

    class NoCallMemory:
        def propose(self, proposal, source_note: str = "mvp-1"):
            raise AssertionError("Memory client should not be called")

        def list_facts(self, scope="global", status="active", **kwargs):
            raise AssertionError("Memory client should not be called")

        def revoke(self, record_id: str) -> None:
            raise AssertionError("Memory client should not be called")

    main(["hello"], llm=llm, memory_client=NoCallMemory())
    captured = capsys.readouterr()
    assert captured.out.strip() == "NO_ACTION"


def test_run_propose(capsys):
    payload = {
        "action": "PROPOSE",
        "subject": "user",
        "predicate": "likes",
        "object": "cats",
        "confidence": 0.9,
    }
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy()

    main(["I like cats"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.propose_calls
    assert "PROPOSED" in captured.out
    assert "subject=user" in captured.out
    assert "predicate=likes" in captured.out
    assert "object=cats" in captured.out


def test_run_retract_found(capsys):
    payload = {
        "action": "RETRACT",
        "subject": "user",
        "predicate": "likes",
        "object": "cats",
        "reason": "no longer true",
    }
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy(
        facts=[{"id": "fact-1", "predicate": "likes", "object": "cats"}]
    )

    main(["I do not like cats"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.list_calls
    assert memory.retract_calls
    assert "RETRACTED fact-1" in captured.out


def test_run_retract_not_found(capsys):
    payload = {
        "action": "RETRACT",
        "subject": "user",
        "predicate": "likes",
        "object": "cats",
        "reason": "no longer true",
    }
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy(facts=[{"id": "fact-1", "predicate": "likes", "object": "dogs"}])

    main(["I do not like cats"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.list_calls
    assert not memory.retract_calls
    assert "NOT_FOUND" in captured.out


def test_run_update_success(capsys):
    payload = {
        "action": "UPDATE",
        "subject": "user",
        "predicate": "likes",
        "old_object": "cats",
        "new_object": "dogs",
        "confidence": 0.8,
        "reason": "preference changed",
    }
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy(
        facts=[{"id": "fact-1", "predicate": "likes", "object": "cats"}]
    )

    main(["I like dogs now"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.list_calls
    assert memory.retract_calls
    assert memory.propose_calls
    assert memory.propose_calls[0]["source_note"] == "update"
    assert "UPDATED fact-1 -> new-123" in captured.out


def test_run_update_not_found(capsys):
    payload = {
        "action": "UPDATE",
        "subject": "user",
        "predicate": "likes",
        "old_object": "cats",
        "new_object": "dogs",
        "confidence": 0.8,
        "reason": "preference changed",
    }
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy(facts=[{"id": "fact-1", "predicate": "likes", "object": "birds"}])

    main(["I like dogs now"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.list_calls
    assert not memory.retract_calls
    assert not memory.propose_calls
    assert "NOT_FOUND_OLD" in captured.out


def test_router_parses_code_fences():
    payload = {
        "action": "PROPOSE",
        "subject": "user",
        "predicate": "likes",
        "object": "tea",
        "confidence": 0.7,
    }
    response = """```json\n{\n  \"action\": \"PROPOSE\",\n  \"subject\": \"user\",\n  \"predicate\": \"likes\",\n  \"object\": \"tea\",\n  \"confidence\": 0.7\n}\n```"""

    decision = parse_llm_output(response)

    assert isinstance(decision, ProposeDecision)
    assert decision.subject == payload["subject"]
    assert decision.predicate == payload["predicate"]
    assert decision.object == payload["object"]
    assert decision.confidence == payload["confidence"]


def test_router_parses_plain_json():
    payload = {
        "action": "PROPOSE",
        "subject": "user",
        "predicate": "likes",
        "object": "cats",
        "confidence": 0.9,
    }

    decision = parse_llm_output(json.dumps(payload))

    assert isinstance(decision, ProposeDecision)
    assert decision.predicate == "likes"


def test_router_parses_fenced_json():
    payload = {
        "action": "PROPOSE",
        "subject": "user",
        "predicate": "likes",
        "object": "tea",
        "confidence": 0.7,
    }
    response = (
        "```json\n"
        "{\n"
        '  "action": "PROPOSE",\n'
        '  "subject": "user",\n'
        '  "predicate": "likes",\n'
        '  "object": "tea",\n'
        '  "confidence": 0.7\n'
        "}\n"
        "```"
    )

    decision = parse_llm_output(response)

    assert isinstance(decision, ProposeDecision)
    assert decision.confidence == payload["confidence"]


def test_router_parses_natural_language_with_fenced_json():
    response = (
        "Sure! Here's the decision:\n"
        "```json\n"
        '{ "action": "PROPOSE", "subject": "user", "predicate": "likes",'
        ' "object": "cats", "confidence": 0.8 }\n'
        "```\n"
        "Thanks!"
    )

    decision = parse_llm_output(response)

    assert isinstance(decision, ProposeDecision)
    assert decision.object == "cats"


def test_router_parses_natural_language_with_inline_json():
    response = (
        "I will store this as memory: "
        '{"action":"PROPOSE","subject":"user","predicate":"likes","object":"cats","confidence":0.8}'
        " done."
    )

    decision = parse_llm_output(response)

    assert isinstance(decision, ProposeDecision)
    assert decision.subject == "user"


def test_router_invalid_json_returns_no_action():
    decision = parse_llm_output("{bad json")
    assert decision.action == "NO_ACTION"


def test_router_prefers_first_action_object():
    response = (
        '{"action":"PROPOSE","subject":"user","predicate":"likes","object":"cats","confidence":0.6}'
        " and later "
        '{"action":"PROPOSE","subject":"user","predicate":"likes","object":"dogs","confidence":0.9}'
    )

    decision = parse_llm_output(response)

    assert isinstance(decision, ProposeDecision)
    assert decision.object == "cats"


def test_execute_decision_propose_failure_traces() -> None:
    class FailingMemory:
        def propose(self, proposal, source_note: str = "mvp-1"):
            raise RuntimeError("connection failed")

        def list_facts(self, subject: str = "user", status: str = "ACTIVE"):
            return []

        def retract(self, record_id: str, reason: str) -> None:
            return None

    decision = ProposeDecision(
        action="PROPOSE",
        subject="user",
        predicate="likes",
        object="cats",
        confidence=0.9,
    )
    trace = TraceCollector(level=TraceLevel.BASIC, trace_id="trace-1")

    status = execute_decision(decision, FailingMemory(), trace=trace)

    assert status == "NO_ACTION"
    assert any(event.stage == "memory.propose.error" for event in trace.events)


def test_router_invalid_json_is_no_action():
    decision = parse_llm_output("```json not-json```")
    assert decision.action == "NO_ACTION"


def test_router_parses_retract_and_update():
    retract_payload = {
        "action": "RETRACT",
        "subject": "user",
        "predicate": "likes",
        "object": "cats",
        "reason": "wrong",
    }
    update_payload = {
        "action": "UPDATE",
        "subject": "user",
        "predicate": "likes",
        "old_object": "cats",
        "new_object": "dogs",
        "confidence": 0.7,
        "reason": "changed",
    }

    retract_decision = parse_llm_output(json.dumps(retract_payload))
    update_decision = parse_llm_output(json.dumps(update_payload))

    assert isinstance(retract_decision, RetractDecision)
    assert isinstance(update_decision, UpdateDecision)
