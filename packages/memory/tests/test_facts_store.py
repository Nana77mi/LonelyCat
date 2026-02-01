import asyncio

import pytest

from memory.facts import FactCandidate, FactStatus, FactsStore


def test_propose_creates_active():
    async def run():
        store = FactsStore()
        candidate = FactCandidate(
            subject="user",
            predicate="likes_cat",
            object=True,
            confidence=0.9,
            source={"session_id": "s1"},
        )
        rec = await store.propose(candidate)
        assert rec.status == FactStatus.ACTIVE
        assert rec.overrides is None
        active = await store.get_active("user", "likes_cat")
        assert active is not None
        assert active.id == rec.id

    asyncio.run(run())


def test_propose_conflict_overrides():
    async def run():
        store = FactsStore()
        first = await store.propose(
            FactCandidate(
                subject="user",
                predicate="likes_cat",
                object=True,
                confidence=0.9,
                source={"session_id": "s1"},
            )
        )
        second = await store.propose(
            FactCandidate(
                subject="user",
                predicate="likes_cat",
                object=False,
                confidence=0.8,
                source={"session_id": "s1"},
            )
        )
        assert second.status == FactStatus.ACTIVE
        assert second.overrides == first.id
        first_after = await store.get(first.id)
        assert first_after is not None
        assert first_after.status == FactStatus.OVERRIDDEN
        active = await store.get_active("user", "likes_cat")
        assert active is not None
        assert active.id == second.id

    asyncio.run(run())


def test_retract_active():
    async def run():
        store = FactsStore()
        rec = await store.propose(
            FactCandidate(
                subject="user",
                predicate="likes_cat",
                object=True,
                confidence=0.9,
                source={"session_id": "s1"},
            )
        )
        await store.retract(rec.id, "no longer true")
        fetched = await store.get(rec.id)
        assert fetched is not None
        assert fetched.status == FactStatus.RETRACTED
        assert fetched.retracted_reason == "no longer true"
        active = await store.get_active("user", "likes_cat")
        assert active is None

    asyncio.run(run())


def test_list_subject_ordering_and_statuses():
    async def run():
        store = FactsStore()
        first = await store.propose(
            FactCandidate(
                subject="user",
                predicate="likes_cat",
                object=True,
                confidence=0.9,
                source={"session_id": "s1"},
            )
        )
        second = await store.propose(
            FactCandidate(
                subject="user",
                predicate="likes_cat",
                object=False,
                confidence=0.8,
                source={"session_id": "s1"},
            )
        )
        third = await store.propose(
            FactCandidate(
                subject="user",
                predicate="age",
                object=7,
                confidence=0.7,
                source={"session_id": "s1"},
            )
        )
        records = await store.list_subject("user")
        assert {record.id for record in records} == {first.id, second.id, third.id}
        ordered = sorted(records, key=lambda record: record.seq)
        assert records == ordered
        statuses = {record.status for record in records}
        assert FactStatus.OVERRIDDEN in statuses
        assert FactStatus.ACTIVE in statuses

    asyncio.run(run())


def test_confidence_validation():
    async def run():
        store = FactsStore()
        with pytest.raises(ValueError):
            await store.propose(
                FactCandidate(
                    subject="user",
                    predicate="likes_cat",
                    object=True,
                    confidence=-0.1,
                    source={"session_id": "s1"},
                )
            )
        with pytest.raises(ValueError):
            await store.propose(
                FactCandidate(
                    subject="user",
                    predicate="likes_cat",
                    object=True,
                    confidence=1.1,
                    source={"session_id": "s1"},
                )
            )

    asyncio.run(run())


def test_concurrency_same_subject_predicate():
    async def run():
        store = FactsStore()
        candidate_one = FactCandidate(
            subject="user",
            predicate="likes_cat",
            object=True,
            confidence=0.9,
            source={"session_id": "s1"},
        )
        candidate_two = FactCandidate(
            subject="user",
            predicate="likes_cat",
            object=False,
            confidence=0.8,
            source={"session_id": "s1"},
        )
        first, second = await asyncio.gather(
            store.propose(candidate_one),
            store.propose(candidate_two),
        )
        records = [first, second]
        active = await store.get_active("user", "likes_cat")
        assert active is not None
        assert (first.overrides is None) ^ (second.overrides is None)
        if active.id == first.id:
            assert first.overrides == second.id
            other = await store.get(second.id)
            assert other is not None
            assert other.status == FactStatus.OVERRIDDEN
        else:
            assert second.overrides == first.id
            other = await store.get(first.id)
            assert other is not None
            assert other.status == FactStatus.OVERRIDDEN

    asyncio.run(run())


def test_external_mutation_does_not_affect_store():
    async def run():
        store = FactsStore()
        rec = await store.propose(
            FactCandidate(
                subject="user",
                predicate="likes_cat",
                object=True,
                confidence=0.9,
                source={"session_id": "s1"},
            )
        )
        rec.status = FactStatus.RETRACTED
        rec.object = "bad"
        rec.source["session_id"] = "mutated"
        active = await store.get_active("user", "likes_cat")
        assert active is not None
        assert active.status == FactStatus.ACTIVE
        assert active.object is True
        assert active.source["session_id"] == "s1"

    asyncio.run(run())


def test_copy_fallback_on_uncopyable_object():
    class Uncopyable:
        def __deepcopy__(self, memo):
            raise RuntimeError("nope")

    async def run():
        store = FactsStore()
        rec = await store.propose(
            FactCandidate(
                subject="user",
                predicate="likes_cat",
                object=Uncopyable(),
                confidence=0.9,
                source={"session_id": "s1"},
            )
        )
        rec.status = FactStatus.RETRACTED
        rec.object = "bad"
        active = await store.get_active("user", "likes_cat")
        assert active is not None
        assert active.status == FactStatus.ACTIVE

    asyncio.run(run())
