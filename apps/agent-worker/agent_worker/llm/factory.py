from __future__ import annotations

import os
from pathlib import Path

from agent_worker.llm.base import BaseLLM, DEFAULT_MAX_PROMPT_CHARS
from agent_worker.llm.json_only import JsonOnlyLLMWrapper
from agent_worker.llm.ollama import OllamaLLM
from agent_worker.llm.openai import OpenAIChatLLM
from agent_worker.llm.qwen import QwenChatLLM
from agent_worker.llm.stub import StubLLM
from agent_worker.llm_config import LLMConfig


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_QWEN_MODEL = "qwen-plus"
DEFAULT_OLLAMA_MODEL = "llama3:8b"


def build_llm(config_path: str | Path | None = None) -> BaseLLM:
    """构建 LLM 实例，优先从配置文件读取，环境变量覆盖配置文件"""
    config = LLMConfig.load(config_path)
    return _build_llm_from_config(config)


def build_llm_from_env() -> BaseLLM:
    """从环境变量构建 LLM 实例（保持向后兼容，现在会自动从配置文件读取）"""
    # 为了向后兼容，现在默认使用新的配置系统（会自动读取配置文件）
    return build_llm()


def build_gate_llm(config_path: str | Path | None = None) -> BaseLLM:
    """构建用于 gate 的 LLM 实例（带 JSON 包装）"""
    return JsonOnlyLLMWrapper(build_llm(config_path))


def build_gate_llm_from_env() -> BaseLLM:
    """从环境变量构建用于 gate 的 LLM 实例（保持向后兼容，现在会自动从配置文件读取）"""
    return build_gate_llm()


def _build_llm_from_config(config: LLMConfig) -> BaseLLM:
    """根据配置对象构建 LLM 实例"""
    provider = config.provider.lower()

    if provider == "stub":
        return StubLLM(max_prompt_chars=config.max_prompt_chars)

    if provider == "openai":
        api_key = config.api_key
        if not api_key:
            raise ValueError("openai provider requires api_key (set in config.yaml or OPENAI_API_KEY env)")
        base_url = config.base_url or "https://api.openai.com/v1"
        return OpenAIChatLLM(
            api_key=api_key,
            model=config.model or DEFAULT_OPENAI_MODEL,
            base_url=base_url,
            timeout_s=config.timeout_s,
            max_retries=config.max_retries,
            retry_backoff_s=config.retry_backoff_s,
            max_prompt_chars=config.max_prompt_chars,
        )

    if provider == "qwen":
        api_key = config.api_key
        if not api_key:
            raise ValueError("qwen provider requires api_key (set in config.yaml or QWEN_API_KEY env)")
        base_url = config.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        return QwenChatLLM(
            api_key=api_key,
            model=config.model or DEFAULT_QWEN_MODEL,
            base_url=base_url,
            timeout_s=config.timeout_s,
            max_retries=config.max_retries,
            retry_backoff_s=config.retry_backoff_s,
            max_prompt_chars=config.max_prompt_chars,
        )

    if provider == "ollama":
        base_url = config.base_url or "http://localhost:11434"
        return OllamaLLM(
            model=config.model or DEFAULT_OLLAMA_MODEL,
            base_url=base_url,
            timeout_s=config.timeout_s,
            max_retries=config.max_retries,
            retry_backoff_s=config.retry_backoff_s,
            max_prompt_chars=config.max_prompt_chars,
        )

    raise ValueError(f"Unsupported LLM provider: {provider}")


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
