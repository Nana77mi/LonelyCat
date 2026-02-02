import httpx
import pytest

from agent_worker.memory_client import MemoryClient


class DummyClient:
    def __init__(self, response: httpx.Response, timeout: float | None = None) -> None:
        self._response = response

    def __enter__(self) -> "DummyClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        return self._response


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, payload) -> None:
    response = httpx.Response(
        200,
        json=payload,
        request=httpx.Request("GET", "http://testserver/memory/facts"),
    )

    def _client_factory(timeout: float | None = None) -> DummyClient:
        return DummyClient(response=response, timeout=timeout)

    monkeypatch.setattr(httpx, "Client", _client_factory)


def test_list_facts_accepts_list_response(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"id": "1"}, {"id": "2"}]
    _patch_httpx_client(monkeypatch, payload)

    client = MemoryClient(base_url="http://testserver")

    assert client.list_facts() == payload


def test_list_facts_accepts_items_response(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"items": [{"id": "1"}]}
    _patch_httpx_client(monkeypatch, payload)

    client = MemoryClient(base_url="http://testserver")

    assert client.list_facts() == payload["items"]


def test_list_facts_accepts_data_response(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"data": [{"id": "1"}]}
    _patch_httpx_client(monkeypatch, payload)

    client = MemoryClient(base_url="http://testserver")

    assert client.list_facts() == payload["data"]


def test_list_facts_rejects_unexpected_response(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"unexpected": "value"}
    _patch_httpx_client(monkeypatch, payload)

    client = MemoryClient(base_url="http://testserver")

    with pytest.raises(ValueError) as excinfo:
        client.list_facts()

    assert "unexpected" in str(excinfo.value)
