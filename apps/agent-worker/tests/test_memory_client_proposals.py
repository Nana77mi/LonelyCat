import httpx
import pytest

from agent_worker.fact_agent import FactProposal
from agent_worker.memory_client import MemoryClient


class DummyClient:
    def __init__(self, response: httpx.Response, timeout: float | None = None) -> None:
        self._response = response

    def __enter__(self) -> "DummyClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, json: dict | None = None) -> httpx.Response:
        return self._response

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        return self._response


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, payload, status_code: int = 200, method: str = "POST") -> None:
    if method == "POST":
        response = httpx.Response(
            status_code,
            json=payload,
            request=httpx.Request("POST", "http://testserver/memory/proposals"),
        )
    else:  # GET
        response = httpx.Response(
            status_code,
            json=payload,
            request=httpx.Request("GET", "http://testserver/memory/facts"),
        )

    def _client_factory(timeout: float | None = None) -> DummyClient:
        return DummyClient(response=response, timeout=timeout)

    monkeypatch.setattr(httpx, "Client", _client_factory)


def test_propose_returns_proposal_id(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "status": "pending",
        "proposal": {"id": "proposal-123", "payload": {"key": "likes", "value": "cats"}},
        "fact": None,
    }
    _patch_httpx_client(monkeypatch, payload)

    client = MemoryClient(base_url="http://testserver")

    assert client.propose(proposal=_fake_proposal()) == "proposal-123"


def test_propose_missing_proposal_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"status": "pending", "proposal": {}, "fact": None}
    _patch_httpx_client(monkeypatch, payload)

    client = MemoryClient(base_url="http://testserver")

    with pytest.raises(ValueError):
        client.propose(proposal=_fake_proposal())


def test_accept_proposal_returns_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "proposal": {"id": "proposal-1", "status": "accepted"},
        "fact": {"id": "fact-1", "key": "likes", "value": "cats", "status": "active"},
    }
    _patch_httpx_client(monkeypatch, payload)

    client = MemoryClient(base_url="http://testserver")

    result = client.accept_proposal("proposal-1")
    assert result == payload


def test_reject_proposal_returns_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"id": "proposal-1", "status": "rejected"}
    _patch_httpx_client(monkeypatch, payload)

    client = MemoryClient(base_url="http://testserver")

    result = client.reject_proposal("proposal-1", reason="no")
    assert result == payload


def test_list_facts_returns_items(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "items": [
            {"id": "fact-1", "key": "likes", "value": "cats", "status": "active"},
            {"id": "fact-2", "key": "prefers", "value": "tea", "status": "active"},
        ]
    }
    _patch_httpx_client(monkeypatch, payload, method="GET")

    client = MemoryClient(base_url="http://testserver")

    facts = client.list_facts(scope="global", status="active")
    assert len(facts) == 2
    assert facts[0]["id"] == "fact-1"
    assert facts[1]["id"] == "fact-2"


def test_list_facts_handles_different_response_formats(monkeypatch: pytest.MonkeyPatch) -> None:
    # 测试 {"data": [...]} 格式
    payload = {
        "data": [
            {"id": "fact-1", "key": "likes", "value": "cats", "status": "active"},
        ]
    }
    _patch_httpx_client(monkeypatch, payload, method="GET")

    client = MemoryClient(base_url="http://testserver")

    facts = client.list_facts(scope="global", status="active")
    assert len(facts) == 1
    assert facts[0]["id"] == "fact-1"


def _fake_proposal() -> FactProposal:
    return FactProposal(
        subject="user",
        predicate="likes",
        object="cats",
        confidence=0.9,
    )
