from __future__ import annotations

import json

from agent_worker.llm.base import BaseLLM
from agent_worker.memory_gate import MEMORY_GATE_MARKER


class StubLLM(BaseLLM):
    def __init__(self, max_prompt_chars: int = 20000) -> None:
        super().__init__(max_prompt_chars=max_prompt_chars)

    def generate(self, prompt: str) -> str:
        prompt = self._trim_prompt(prompt)
        if MEMORY_GATE_MARKER in prompt:
            return "NO_ACTION"
        return json.dumps({"assistant_reply": "Okay.", "memory": "NO_ACTION"})

    def generate_messages(self, messages: list[dict[str, str]]) -> str:
        """Generate response from a list of messages."""
        # Check if any message contains MEMORY_GATE_MARKER
        for msg in messages:
            content = msg.get("content", "")
            if MEMORY_GATE_MARKER in content:
                return "NO_ACTION"
        return json.dumps({"assistant_reply": "Okay.", "memory": "NO_ACTION"})
