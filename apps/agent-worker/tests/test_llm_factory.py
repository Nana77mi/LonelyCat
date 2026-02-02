import pytest

from agent_worker.llm.factory import build_llm_from_env
from agent_worker.llm.stub import StubLLM


def test_factory_defaults_to_stub(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
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
