import json

from agent_worker.llm.json_only import JsonOnlyLLMWrapper


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate(self, prompt: str) -> str:
        return self.response


def test_json_only_returns_no_action_on_non_json():
    llm = JsonOnlyLLMWrapper(FakeLLM("hello"))  # type: ignore[arg-type]

    assert llm.generate("prompt") == "NO_ACTION"


def test_json_only_strips_code_fences():
    payload = {"action": "PROPOSE", "subject": "user", "predicate": "likes", "object": "tea"}
    response = f"```json\n{json.dumps(payload)}\n```"
    llm = JsonOnlyLLMWrapper(FakeLLM(response))  # type: ignore[arg-type]

    assert llm.generate("prompt") == json.dumps(payload, separators=(",", ":"))
