import json

import agent_worker.chat as chat
from agent_worker.fact_agent import FactProposal


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


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


class PromptInspectingLLM:
    def __init__(self) -> None:
        self.prompts = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "You are LonelyCat" in prompt:
            reply = "Warm hello."
        elif "You are ProfessionalAssistant" in prompt:
            reply = "Professional hello."
        else:
            reply = "Default hello."
        return json.dumps({"assistant_reply": reply, "memory": "NO_ACTION"})


def test_chat_no_action(capsys):
    payload = {"assistant_reply": "Hello!", "memory": "NO_ACTION"}
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy()

    chat.main(["Hi"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.list_calls
    assert not memory.propose_calls
    assert not memory.retract_calls
    assert "Hello!" in captured.out
    assert "MEMORY: NO_ACTION" in captured.out


def test_chat_propose(capsys):
    payload = {
        "assistant_reply": "Great to know.",
        "memory": {
            "action": "PROPOSE",
            "subject": "user",
            "predicate": "likes",
            "object": "cats",
            "confidence": 0.9,
        },
    }
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy()

    chat.main(["I like cats"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.list_calls
    assert memory.propose_calls
    call = memory.propose_calls[0]
    assert call["proposal"].subject == "user"
    assert call["proposal"].predicate == "likes"
    assert call["proposal"].object == "cats"
    assert call["source_note"] == "chat"
    assert "MEMORY: PROPOSED" in captured.out


def test_chat_retract(capsys):
    payload = {
        "assistant_reply": "Understood.",
        "memory": {
            "action": "RETRACT",
            "subject": "user",
            "predicate": "likes",
            "object": "cats",
            "reason": "no longer true",
        },
    }
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy(
        facts=[{"id": "fact-1", "predicate": "likes", "object": "cats"}]
    )

    chat.main(["I don't like cats"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.list_calls
    assert memory.retract_calls
    assert "MEMORY: RETRACTED fact-1" in captured.out


def test_chat_update(capsys):
    payload = {
        "assistant_reply": "Got it.",
        "memory": {
            "action": "UPDATE",
            "subject": "user",
            "predicate": "likes",
            "old_object": "cats",
            "new_object": "dogs",
            "confidence": 0.8,
            "reason": "preference changed",
        },
    }
    llm = FakeLLM(json.dumps(payload))
    memory = MemorySpy(
        facts=[{"id": "fact-1", "predicate": "likes", "object": "cats"}]
    )

    chat.main(["I like dogs now"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.list_calls
    assert memory.retract_calls
    assert memory.propose_calls
    assert memory.propose_calls[0]["source_note"] == "update"
    assert "MEMORY: UPDATED fact-1 -> new-123" in captured.out


def test_chat_invalid_json_is_no_action(capsys):
    llm = FakeLLM("not json at all")
    memory = MemorySpy()

    chat.main(["Hi"], llm=llm, memory_client=memory)
    captured = capsys.readouterr()

    assert memory.list_calls
    assert not memory.propose_calls
    assert not memory.retract_calls
    assert "not json at all" in captured.out
    assert "MEMORY: NO_ACTION" in captured.out


def test_chat_persona_hot_swap_no_action():
    llm = PromptInspectingLLM()
    memory = MemorySpy()

    reply_lonely, status_lonely = chat.chat(
        "Hi", persona_id="lonelycat", llm=llm, memory_client=memory
    )
    reply_professional, status_professional = chat.chat(
        "Hi", persona_id="professional", llm=llm, memory_client=memory
    )

    assert status_lonely == "NO_ACTION"
    assert status_professional == "NO_ACTION"
    assert reply_lonely != reply_professional


def test_chat_persona_only_changes_reply_not_memory():
    llm = PromptInspectingLLM()
    memory = MemorySpy()

    reply_lonely, status_lonely = chat.chat(
        "Hello", persona_id="lonelycat", llm=llm, memory_client=memory
    )
    reply_professional, status_professional = chat.chat(
        "Hello", persona_id="professional", llm=llm, memory_client=memory
    )

    assert reply_lonely != reply_professional
    assert status_lonely == "NO_ACTION"
    assert status_professional == "NO_ACTION"
    assert not memory.propose_calls
    assert not memory.retract_calls


def test_chat_persona_missing_or_unknown_falls_back_to_default():
    llm = PromptInspectingLLM()
    memory = MemorySpy()

    reply_missing, status_missing = chat.chat(
        "Hello", llm=llm, memory_client=memory
    )
    reply_unknown, status_unknown = chat.chat(
        "Hello", persona_id="unknown-id", llm=llm, memory_client=memory
    )

    assert reply_missing == "Warm hello."
    assert reply_unknown == "Warm hello."
    assert status_missing == "NO_ACTION"
    assert status_unknown == "NO_ACTION"
