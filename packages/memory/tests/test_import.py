import memory
from memory.facts import FactsStore


def test_facts_store_importable():
    store = FactsStore()
    assert isinstance(store, FactsStore)
    assert hasattr(memory, "FactsStore")
