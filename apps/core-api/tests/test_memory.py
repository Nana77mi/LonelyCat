import asyncio

import pytest
from fastapi import HTTPException

from app.api import memory
from memory.facts import FactsStore


def assert_fact_schema(record: dict, status: str) -> None:
    base_keys = {
        "id",
        "subject",
        "predicate",
        "object",
        "confidence",
        "status",
        "created_at",
        "seq",
    }
    if status == "OVERRIDDEN":
        expected = base_keys | {"overrides"}
    elif status == "RETRACTED":
        expected = base_keys | {"retracted_reason"}
    else:
        expected = base_keys
    assert set(record.keys()) == expected
    assert record["status"] == status


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
    assert_fact_schema(record, "ACTIVE")

    response = asyncio.run(memory.list_facts(store=store))
    assert len(response["items"]) == 1
    assert response["items"][0]["id"] == record["id"]
    assert_fact_schema(response["items"][0], "ACTIVE")


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
    assert_fact_schema(fetched, "ACTIVE")


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
    assert_fact_schema(retracted, "RETRACTED")

    fetched = asyncio.run(memory.get_fact(record["id"], store=store))
    assert fetched["status"] == "RETRACTED"
    assert fetched["retracted_reason"] == "no longer true"
    assert_fact_schema(fetched, "RETRACTED")


def test_retract_missing_raises() -> None:
    store = FactsStore()
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            memory.retract_fact(
                "missing",
                memory.RetractRequest(reason="reason"),
                store=store,
            )
        )
    assert excinfo.value.status_code == 404


def test_retract_already_retracted_raises() -> None:
    store = FactsStore()
    candidate = memory.FactCandidateIn(
        subject="user",
        predicate="tool",
        object="git",
        confidence=0.9,
        source={"type": "test"},
    )
    record = asyncio.run(memory.propose_fact(candidate, store=store))
    asyncio.run(
        memory.retract_fact(
            record["id"],
            memory.RetractRequest(reason="no longer true"),
            store=store,
        )
    )
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            memory.retract_fact(
                record["id"],
                memory.RetractRequest(reason="again"),
                store=store,
            )
        )
    assert excinfo.value.status_code == 400


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
    assert_fact_schema(record, "ACTIVE")


def test_propose_twice_overrides_previous() -> None:
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

    assert second_record["status"] == "ACTIVE"
    assert_fact_schema(second_record, "ACTIVE")

    response = asyncio.run(memory.list_facts(store=store))
    assert len(response["items"]) == 2
    assert response["items"][0]["id"] == first_record["id"]
    assert response["items"][1]["id"] == second_record["id"]
    overridden = response["items"][0]
    assert overridden["status"] == "OVERRIDDEN"
    assert_fact_schema(overridden, "OVERRIDDEN")


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
    assert_fact_schema(chain["items"][0], "ACTIVE")
    assert_fact_schema(chain["items"][1], "OVERRIDDEN")


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


def test_chain_cycle_is_detected_and_truncated() -> None:
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

    store._records[first_record["id"]].overrides = second_record["id"]

    chain = asyncio.run(
        memory.get_fact_chain(second_record["id"], max_depth=20, store=store)
    )
    assert chain["truncated"] is True
    assert len(chain["items"]) <= 20
