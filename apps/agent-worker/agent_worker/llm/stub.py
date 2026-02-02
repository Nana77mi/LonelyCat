from __future__ import annotations

import json

from agent_worker.llm.base import BaseLLM


class StubLLM(BaseLLM):
    def generate(self, prompt: str) -> str:
        return json.dumps({"assistant_reply": "Okay.", "memory": "NO_ACTION"})
