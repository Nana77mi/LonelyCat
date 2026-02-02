from __future__ import annotations

from agent_worker.llm.base import BaseLLM


class QwenLLM(BaseLLM):
    def generate(self, prompt: str) -> str:
        raise RuntimeError("QwenLLM is not configured in this environment")
