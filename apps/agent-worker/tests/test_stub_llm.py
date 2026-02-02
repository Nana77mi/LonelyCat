import json

from agent_worker.llm.stub import StubLLM
from agent_worker.memory_gate import MemoryGate, parse_gate_output
from agent_worker.persona import PersonaRegistry
from agent_worker.responder import Responder, parse_responder_output
from agent_worker.router import NoActionDecision


def test_stub_llm_responder_reply():
    llm = StubLLM()
    responder = Responder(llm)
    persona = PersonaRegistry.load_default().default()

    reply, memory_hint = responder.reply(persona, "Hello", [])

    assert isinstance(reply, str)
    assert reply == "Okay."
    assert memory_hint == "NO_ACTION"


def test_stub_llm_gate_no_action():
    llm = StubLLM()
    gate = MemoryGate(llm)

    decision = gate.decide("Hello", [])

    assert isinstance(decision, NoActionDecision)


def test_responder_parses_gate_output_as_text():
    reply, memory_hint = parse_responder_output("NO_ACTION")

    assert reply == "NO_ACTION"
    assert memory_hint == "NO_ACTION"


def test_gate_ignores_responder_json():
    responder_payload = json.dumps({"assistant_reply": "Okay.", "memory": "NO_ACTION"})

    decision = parse_gate_output(responder_payload)

    assert isinstance(decision, NoActionDecision)
