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


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, payload, status_code: int = 200) -> None:
    response = httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", "http://testserver/memory/facts/propose"),
    )

    def _client_factory(timeout: float | None = None) -> DummyClient:
        return DummyClient(response=response, timeout=timeout)

    monkeypatch.setattr(httpx, "Client", _client_factory)


def test_propose_returns_proposal_id(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "status": "PENDING",
        "proposal": {"id": "proposal-123"},
        "record": None,
    }
    _patch_httpx_client(monkeypatch, payload)

    client = MemoryClient(base_url="http://testserver")

    assert client.propose(proposal=_fake_proposal()) == "proposal-123"


def test_propose_missing_proposal_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"status": "PENDING", "proposal": {"id": ""}, "record": None}
    _patch_httpx_client(monkeypatch, payload)

    client = MemoryClient(base_url="http://testserver")

    with pytest.raises(ValueError):
        client.propose(proposal=_fake_proposal())


def test_accept_and_reject_return_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"proposal": {"id": "proposal-1"}, "record": {"id": "fact-1"}}
    _patch_httpx_client(monkeypatch, payload)

    client = MemoryClient(base_url="http://testserver")

    assert client.accept_proposal("proposal-1") == payload
    assert client.reject_proposal("proposal-1", reason="no") == payload


def _fake_proposal() -> FactProposal:
    return FactProposal(
        subject="user",
        predicate="likes",
        object="cats",
        confidence=0.9,
    )
