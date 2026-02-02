from __future__ import annotations

import json

from agent_worker.llm.base import BaseLLM
from agent_worker.memory_gate import MEMORY_GATE_MARKER


class StubLLM(BaseLLM):
    def generate(self, prompt: str) -> str:
        if MEMORY_GATE_MARKER in prompt:
            return "NO_ACTION"
        return json.dumps({"assistant_reply": "Okay.", "memory": "NO_ACTION"})
