from __future__ import annotations

from agent_worker.llm.base import BaseLLM


class LocalLLM(BaseLLM):
    def generate(self, prompt: str) -> str:
        raise RuntimeError("LocalLLM is not configured in this environment")
