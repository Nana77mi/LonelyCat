import httpx
import pytest

from agent_worker.llm.factory import build_llm_from_env
from agent_worker.llm.openai import OpenAIChatLLM
from agent_worker.llm.ollama import OllamaLLM
from agent_worker.llm.stub import StubLLM


def test_factory_defaults_to_stub(monkeypatch):
    """When LLM_PROVIDER is stub, factory returns StubLLM (explicit stub overrides config file)."""
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    llm = build_llm_from_env()
    assert isinstance(llm, StubLLM)


def test_factory_stub_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    llm = build_llm_from_env()
    assert isinstance(llm, StubLLM)


def test_factory_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    with pytest.raises(ValueError):
        build_llm_from_env()


def test_factory_openai_missing_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError):
        build_llm_from_env()


def test_factory_qwen_missing_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    with pytest.raises(ValueError):
        build_llm_from_env()


def test_factory_ollama_defaults_base_url(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    llm = build_llm_from_env()
    assert isinstance(llm, OllamaLLM)


def test_openai_retries_on_429():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"error": "rate limit"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hello"}}]},
        )

    transport = httpx.MockTransport(handler)
    llm = OpenAIChatLLM(
        api_key="test-key",
        model="gpt-4o-mini",
        base_url="https://example.com",
        timeout_s=1.0,
        max_retries=2,
        retry_backoff_s=0.0,
        transport=transport,
    )

    assert llm.generate("hi") == "hello"
    assert calls["count"] == 2
