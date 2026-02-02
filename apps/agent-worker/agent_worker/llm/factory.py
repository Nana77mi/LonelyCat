from __future__ import annotations

import os

from agent_worker.llm.base import BaseLLM
from agent_worker.llm.local import LocalLLM
from agent_worker.llm.openai import OpenAILLM
from agent_worker.llm.qwen import QwenLLM
from agent_worker.llm.stub import StubLLM


def build_llm_from_env() -> BaseLLM:
    provider = os.getenv("LLM_PROVIDER", "stub").lower()
    if provider == "stub":
        return StubLLM()
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY must be set for openai provider")
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        return OpenAILLM(api_key=api_key, model=model)
    if provider == "qwen":
        return QwenLLM()
    if provider == "local":
        return LocalLLM()
    raise ValueError(f"Unsupported LLM provider: {provider}")
