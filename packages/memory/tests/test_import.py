import memory
from memory.facts import MemoryStore


def test_memory_store_importable():
    store = MemoryStore()
    assert isinstance(store, MemoryStore)
    assert hasattr(memory, "MemoryStore")
