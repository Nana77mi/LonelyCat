from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


@dataclass(frozen=True)
class LLMConfig:
    """LLM 配置类，支持从配置文件和环境变量读取"""

    provider: str = "stub"
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_s: float = 30.0
    max_retries: int = 2
    retry_backoff_s: float = 0.8
    max_prompt_chars: int = 20000

    @classmethod
    def from_config_file(cls, config_path: str | Path | None = None) -> LLMConfig | None:
        """从配置文件读取配置"""
        if yaml is None:
            return None

        if config_path is None:
            # 默认查找项目根目录下的 configs/config.yaml
            repo_root = Path(__file__).parent.parent.parent.parent
            config_path = repo_root / "configs" / "config.yaml"

        config_path = Path(config_path)
        if not config_path.exists():
            return None

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)
        except Exception:
            return None

        if not config_data or "models" not in config_data:
            return None

        models_config = config_data["models"]
        provider = models_config.get("provider", "stub")
        default_model = models_config.get("default", "stub")

        # 根据 provider 获取对应的配置
        provider_config = models_config.get(provider, {})
        model = provider_config.get("model") or default_model
        base_url = provider_config.get("base_url")
        api_key = provider_config.get("api_key") or ""

        # 读取通用配置
        timeout_s = models_config.get("timeout_s", 30.0)
        max_retries = models_config.get("max_retries", 2)
        retry_backoff_s = models_config.get("retry_backoff_s", 0.8)
        max_prompt_chars = models_config.get("max_prompt_chars", 20000)

        return cls(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key if api_key else None,
            timeout_s=timeout_s,
            max_retries=max_retries,
            retry_backoff_s=retry_backoff_s,
            max_prompt_chars=max_prompt_chars,
        )

    @classmethod
    def from_env(cls) -> LLMConfig:
        """从环境变量读取配置（优先级最高）"""
        provider = os.getenv("LLM_PROVIDER", "stub").lower()
        model = os.getenv("LLM_MODEL")
        base_url = os.getenv("LLM_BASE_URL")

        # 根据 provider 获取对应的 API key 和 base_url
        api_key = None
        if provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not base_url:
                base_url = os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        elif provider == "qwen":
            api_key = os.getenv("QWEN_API_KEY")
            if not base_url:
                base_url = (
                    os.getenv("QWEN_BASE_URL")
                    or "https://dashscope.aliyuncs.com/compatible-mode/v1"
                )
        elif provider == "ollama":
            if not base_url:
                base_url = os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434"

        timeout_s = _env_float("LLM_TIMEOUT_S", 30.0)
        max_retries = _env_int("LLM_MAX_RETRIES", 2)
        retry_backoff_s = _env_float("LLM_RETRY_BACKOFF_S", 0.8)
        max_prompt_chars = _env_int("LLM_MAX_PROMPT_CHARS", 20000)

        return cls(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout_s=timeout_s,
            max_retries=max_retries,
            retry_backoff_s=retry_backoff_s,
            max_prompt_chars=max_prompt_chars,
        )

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> LLMConfig:
        """加载配置，环境变量优先，然后配置文件"""
        # 先尝试从配置文件读取（作为默认值）
        file_config = cls.from_config_file(config_path)
        
        # 从环境变量读取（优先级更高）
        env_config = cls.from_env()

        # 如果环境变量中明确指定了 provider，完全使用环境变量配置
        if os.getenv("LLM_PROVIDER"):
            return env_config

        # 否则合并配置：环境变量覆盖配置文件，配置文件作为默认值
        if file_config:
            return cls(
                provider=env_config.provider if env_config.provider != "stub" else file_config.provider,
                model=env_config.model or file_config.model,
                base_url=env_config.base_url or file_config.base_url,
                api_key=env_config.api_key or file_config.api_key,
                timeout_s=env_config.timeout_s if os.getenv("LLM_TIMEOUT_S") else file_config.timeout_s,
                max_retries=env_config.max_retries if os.getenv("LLM_MAX_RETRIES") else file_config.max_retries,
                retry_backoff_s=env_config.retry_backoff_s if os.getenv("LLM_RETRY_BACKOFF_S") else file_config.retry_backoff_s,
                max_prompt_chars=env_config.max_prompt_chars if os.getenv("LLM_MAX_PROMPT_CHARS") else file_config.max_prompt_chars,
            )

        # 如果配置文件不存在，返回环境变量配置（默认 stub）
        return env_config


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
