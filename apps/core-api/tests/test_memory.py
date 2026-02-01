import asyncio

from app.api import memory
from memory.facts import FactsStore


def test_list_empty() -> None:
    store = FactsStore()
    response = asyncio.run(memory.list_facts(store=store))
    assert response == {"items": []}


def test_propose_then_list() -> None:
    store = FactsStore()
    candidate = memory.FactCandidateIn(
        subject="user",
        predicate="likes",
        object="coffee",
        confidence=0.9,
        source={"type": "test"},
    )
    record = asyncio.run(memory.propose_fact(candidate, store=store))
    assert record["predicate"] == "likes"
    assert record["status"] == "ACTIVE"

    response = asyncio.run(memory.list_facts(store=store))
    assert len(response["items"]) == 1
    assert response["items"][0]["id"] == record["id"]


def test_get_by_id() -> None:
    store = FactsStore()
    candidate = memory.FactCandidateIn(
        subject="user",
        predicate="prefers",
        object="tea",
        confidence=0.75,
        source={"type": "test"},
    )
    record = asyncio.run(memory.propose_fact(candidate, store=store))

    fetched = asyncio.run(memory.get_fact(record["id"], store=store))
    assert fetched["id"] == record["id"]
    assert fetched["object"] == "tea"


def test_retract() -> None:
    store = FactsStore()
    candidate = memory.FactCandidateIn(
        subject="user",
        predicate="uses",
        object="vim",
        confidence=0.5,
        source={"type": "test"},
    )
    record = asyncio.run(memory.propose_fact(candidate, store=store))

    retracted = asyncio.run(
        memory.retract_fact(
            record["id"],
            memory.RetractRequest(reason="no longer true"),
            store=store,
        )
    )
    assert retracted["status"] == "RETRACTED"
    assert retracted["retracted_reason"] == "no longer true"


def test_non_json_object_is_stringified() -> None:
    store = FactsStore()

    class NotSerializable:
        def __repr__(self) -> str:
            return "NotSerializable()"

    candidate = memory.FactCandidateIn(
        subject="user",
        predicate="test",
        object=NotSerializable(),
        confidence=0.4,
        source={"type": "test"},
    )

    record = asyncio.run(memory.propose_fact(candidate, store=store))
    assert isinstance(record["object"], str)


def test_chain_endpoint_returns_root_and_overrides() -> None:
    store = FactsStore()
    first = memory.FactCandidateIn(
        subject="user",
        predicate="prefers",
        object="tea",
        confidence=0.5,
        source={"type": "test"},
    )
    second = memory.FactCandidateIn(
        subject="user",
        predicate="prefers",
        object="coffee",
        confidence=0.6,
        source={"type": "test"},
    )
    first_record = asyncio.run(memory.propose_fact(first, store=store))
    second_record = asyncio.run(memory.propose_fact(second, store=store))

    chain = asyncio.run(
        memory.get_fact_chain(second_record["id"], max_depth=20, store=store)
    )
    assert chain["root_id"] == second_record["id"]
    assert len(chain["items"]) == 2
    assert chain["items"][0]["id"] == second_record["id"]
    assert chain["items"][1]["id"] == first_record["id"]
    assert chain["truncated"] is False


def test_chain_endpoint_max_depth_truncates() -> None:
    store = FactsStore()
    last_record = None
    for idx in range(5):
        candidate = memory.FactCandidateIn(
            subject="user",
            predicate="language",
            object=f"lang-{idx}",
            confidence=0.5,
            source={"type": "test"},
        )
        last_record = asyncio.run(memory.propose_fact(candidate, store=store))
    assert last_record is not None

    chain = asyncio.run(
        memory.get_fact_chain(last_record["id"], max_depth=2, store=store)
    )
    assert len(chain["items"]) == 2
    assert chain["truncated"] is True
