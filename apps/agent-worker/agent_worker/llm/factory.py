from __future__ import annotations

import os

from agent_worker.llm.base import BaseLLM, DEFAULT_MAX_PROMPT_CHARS
from agent_worker.llm.json_only import JsonOnlyLLMWrapper
from agent_worker.llm.ollama import OllamaLLM
from agent_worker.llm.openai import OpenAIChatLLM
from agent_worker.llm.qwen import QwenChatLLM
from agent_worker.llm.stub import StubLLM


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_QWEN_MODEL = "qwen-plus"
DEFAULT_OLLAMA_MODEL = "llama3:8b"


def build_llm_from_env() -> BaseLLM:
    provider = os.getenv("LLM_PROVIDER", "stub").lower()
    max_prompt_chars = _env_int("LLM_MAX_PROMPT_CHARS", DEFAULT_MAX_PROMPT_CHARS)
    timeout_s = _env_float("LLM_TIMEOUT_S", 30.0)
    max_retries = _env_int("LLM_MAX_RETRIES", 2)
    retry_backoff_s = _env_float("LLM_RETRY_BACKOFF_S", 0.8)
    model = os.getenv("LLM_MODEL")
    base_url = os.getenv("LLM_BASE_URL")

    if provider == "stub":
        return StubLLM(max_prompt_chars=max_prompt_chars)
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("openai provider requires OPENAI_API_KEY")
        openai_base = os.getenv("OPENAI_BASE_URL") or base_url or "https://api.openai.com/v1"
        return OpenAIChatLLM(
            api_key=api_key,
            model=model or DEFAULT_OPENAI_MODEL,
            base_url=openai_base,
            timeout_s=timeout_s,
            max_retries=max_retries,
            retry_backoff_s=retry_backoff_s,
            max_prompt_chars=max_prompt_chars,
        )
    if provider == "qwen":
        api_key = os.getenv("QWEN_API_KEY")
        if not api_key:
            raise ValueError("qwen provider requires QWEN_API_KEY")
        qwen_base = (
            os.getenv("QWEN_BASE_URL")
            or base_url
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        return QwenChatLLM(
            api_key=api_key,
            model=model or DEFAULT_QWEN_MODEL,
            base_url=qwen_base,
            timeout_s=timeout_s,
            max_retries=max_retries,
            retry_backoff_s=retry_backoff_s,
            max_prompt_chars=max_prompt_chars,
        )
    if provider == "ollama":
        ollama_base = os.getenv("OLLAMA_BASE_URL") or base_url or "http://localhost:11434"
        return OllamaLLM(
            model=model or DEFAULT_OLLAMA_MODEL,
            base_url=ollama_base,
            timeout_s=timeout_s,
            max_retries=max_retries,
            retry_backoff_s=retry_backoff_s,
            max_prompt_chars=max_prompt_chars,
        )
    raise ValueError(f"Unsupported LLM provider: {provider}")


def build_gate_llm_from_env() -> BaseLLM:
    return JsonOnlyLLMWrapper(build_llm_from_env())


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default
