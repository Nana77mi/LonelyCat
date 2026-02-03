"""Cross-module consistency: core-api and agent-worker compute_facts_snapshot_id must match.

Same canonical rules (id, key, value; status==active; sort by id then key) so run input
from core-api and worker output stay comparable. Run with make test-py from repo root
so both apps are installed.
"""

import pytest

from app.services.facts import compute_facts_snapshot_id as core_api_snapshot_id

try:
    from agent_worker.utils.facts_format import compute_facts_snapshot_id as worker_snapshot_id
    _WORKER_AVAILABLE = True
except ImportError:
    worker_snapshot_id = None  # type: ignore
    _WORKER_AVAILABLE = False


@pytest.mark.skipif(not _WORKER_AVAILABLE, reason="agent_worker not installed (run from repo root)")
def test_snapshot_id_core_api_equals_worker_empty():
    """Empty facts: core-api and worker must produce the same snapshot_id."""
    facts = []
    assert core_api_snapshot_id(facts) == worker_snapshot_id(facts)


@pytest.mark.skipif(not _WORKER_AVAILABLE, reason="agent_worker not installed (run from repo root)")
def test_snapshot_id_core_api_equals_worker_single():
    """Single fact: core-api and worker must produce the same snapshot_id."""
    facts = [{"key": "likes", "value": "cats", "status": "active"}]
    assert core_api_snapshot_id(facts) == worker_snapshot_id(facts)


@pytest.mark.skipif(not _WORKER_AVAILABLE, reason="agent_worker not installed (run from repo root)")
def test_snapshot_id_core_api_equals_worker_two_order_independent():
    """Two facts, different order: both sides same id, and core-api == worker."""
    facts1 = [
        {"key": "likes", "value": "cats", "status": "active"},
        {"key": "language", "value": "zh-CN", "status": "active"},
    ]
    facts2 = [
        {"key": "language", "value": "zh-CN", "status": "active"},
        {"key": "likes", "value": "cats", "status": "active"},
    ]
    core1 = core_api_snapshot_id(facts1)
    core2 = core_api_snapshot_id(facts2)
    worker1 = worker_snapshot_id(facts1)
    worker2 = worker_snapshot_id(facts2)
    assert core1 == core2, "core-api: same set different order → same id"
    assert worker1 == worker2, "worker: same set different order → same id"
    assert core1 == worker1, "core-api id == worker id"


@pytest.mark.skipif(not _WORKER_AVAILABLE, reason="agent_worker not installed (run from repo root)")
def test_snapshot_id_core_api_equals_worker_with_extra_fields():
    """Facts with extra fields (created_at, etc.): canonical uses only id/key/value."""
    facts = [
        {
            "id": "f1",
            "key": "likes",
            "value": "cats",
            "status": "active",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-02T00:00:00Z",
        },
    ]
    assert core_api_snapshot_id(facts) == worker_snapshot_id(facts)
