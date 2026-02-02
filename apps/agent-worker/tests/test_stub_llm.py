import json

from agent_worker.llm.stub import StubLLM


def test_stub_llm_returns_json():
    llm = StubLLM()
    payload = json.loads(llm.generate("hello"))

    assert payload == {"assistant_reply": "Okay.", "memory": "NO_ACTION"}
