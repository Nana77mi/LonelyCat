"""
Test Lineage API Endpoints - Phase 2.4-A

Validates:
- GET /executions/{execution_id}/lineage
- GET /executions/correlation/{correlation_id}
- GET /executions?correlation_id=...
"""

import pytest
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

# Add packages to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "packages"))

from executor import ExecutionStore, init_executor_db


@pytest.fixture
def temp_workspace():
    """Create temporary workspace with database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        db_path = workspace / ".lonelycat" / "executor.db"
        init_executor_db(db_path)
        yield workspace


@pytest.fixture
def execution_store(temp_workspace):
    """Create ExecutionStore."""
    return ExecutionStore(temp_workspace)


@pytest.fixture
def api_client(temp_workspace):
    """Create FastAPI test client."""
    # Patch the global execution store in the API module
    from app.api import executions as exec_api
    original_store = exec_api.execution_store
    exec_api.execution_store = ExecutionStore(temp_workspace)

    from app.main import app
    client = TestClient(app)

    yield client

    # Restore original store
    exec_api.execution_store = original_store


def create_execution_chain(store: ExecutionStore, workspace: Path):
    """
    Create a chain of executions for testing:
    root -> child1 -> grandchild
                   -> child2
    """
    # Root execution
    store.record_execution_start(
        execution_id="exec_root",
        plan_id="plan_1",
        changeset_id="cs_1",
        decision_id="dec_1",
        checksum="sum_1",
        verdict="allow",
        risk_level="low",
        affected_paths=[],
        artifact_path=str(workspace / "exec_root"),
        correlation_id="corr_chain",
        parent_execution_id=None,
        trigger_kind="manual"
    )
    store.record_execution_complete("exec_root", files_changed=1)

    # Child 1
    store.record_execution_start(
        execution_id="exec_child1",
        plan_id="plan_2",
        changeset_id="cs_2",
        decision_id="dec_2",
        checksum="sum_2",
        verdict="allow",
        risk_level="low",
        affected_paths=[],
        artifact_path=str(workspace / "exec_child1"),
        correlation_id="corr_chain",
        parent_execution_id="exec_root",
        trigger_kind="retry"
    )
    store.record_execution_complete("exec_child1", files_changed=2)

    # Child 2 (sibling)
    store.record_execution_start(
        execution_id="exec_child2",
        plan_id="plan_3",
        changeset_id="cs_3",
        decision_id="dec_3",
        checksum="sum_3",
        verdict="allow",
        risk_level="low",
        affected_paths=[],
        artifact_path=str(workspace / "exec_child2"),
        correlation_id="corr_chain",
        parent_execution_id="exec_root",
        trigger_kind="repair"
    )
    store.record_execution_complete("exec_child2", files_changed=1)

    # Grandchild
    store.record_execution_start(
        execution_id="exec_grandchild",
        plan_id="plan_4",
        changeset_id="cs_4",
        decision_id="dec_4",
        checksum="sum_4",
        verdict="allow",
        risk_level="low",
        affected_paths=[],
        artifact_path=str(workspace / "exec_grandchild"),
        correlation_id="corr_chain",
        parent_execution_id="exec_child1",
        trigger_kind="retry"
    )
    store.record_execution_complete("exec_grandchild", files_changed=3)


def test_get_execution_lineage(api_client, execution_store, temp_workspace):
    """Test GET /executions/{execution_id}/lineage."""
    # Setup: Create execution chain
    create_execution_chain(execution_store, temp_workspace)

    # Test: Get lineage for child1
    response = api_client.get("/executions/exec_child1/lineage")

    assert response.status_code == 200
    data = response.json()

    # Verify structure
    assert "execution" in data
    assert "ancestors" in data
    assert "descendants" in data
    assert "siblings" in data

    # Verify execution
    assert data["execution"]["execution_id"] == "exec_child1"
    assert data["execution"]["correlation_id"] == "corr_chain"
    assert data["execution"]["parent_execution_id"] == "exec_root"
    assert data["execution"]["trigger_kind"] == "retry"

    # Verify ancestors (should have 1: root)
    assert len(data["ancestors"]) == 1
    assert data["ancestors"][0]["execution_id"] == "exec_root"

    # Verify descendants (should have 1: grandchild)
    assert len(data["descendants"]) == 1
    assert data["descendants"][0]["execution_id"] == "exec_grandchild"

    # Verify siblings (should have 1: child2)
    assert len(data["siblings"]) == 1
    assert data["siblings"][0]["execution_id"] == "exec_child2"

    print("[OK] Lineage API: ancestors=1, descendants=1, siblings=1")


def test_get_correlation_chain(api_client, execution_store, temp_workspace):
    """Test GET /executions/correlation/{correlation_id}."""
    # Setup: Create execution chain
    create_execution_chain(execution_store, temp_workspace)

    # Test: Get correlation chain
    response = api_client.get("/executions/correlation/corr_chain")

    assert response.status_code == 200
    data = response.json()

    # Verify structure
    assert data["correlation_id"] == "corr_chain"
    assert data["total_executions"] == 4
    assert data["root_execution_id"] == "exec_root"
    assert len(data["executions"]) == 4

    # Verify all executions present
    exec_ids = {e["execution_id"] for e in data["executions"]}
    assert exec_ids == {"exec_root", "exec_child1", "exec_child2", "exec_grandchild"}

    print(f"[OK] Correlation Chain: {data['total_executions']} executions")


def test_list_executions_by_correlation(api_client, execution_store, temp_workspace):
    """Test GET /executions?correlation_id=..."""
    # Setup: Create execution chain
    create_execution_chain(execution_store, temp_workspace)

    # Test: List executions by correlation_id
    response = api_client.get("/executions?correlation_id=corr_chain")

    assert response.status_code == 200
    data = response.json()

    # Verify structure
    assert "executions" in data
    assert data["total"] == 4
    assert len(data["executions"]) == 4

    # Verify all executions present
    exec_ids = {e["execution_id"] for e in data["executions"]}
    assert exec_ids == {"exec_root", "exec_child1", "exec_child2", "exec_grandchild"}

    print(f"[OK] List by correlation_id: {data['total']} executions")


def test_lineage_not_found(api_client):
    """Test 404 for non-existent execution."""
    response = api_client.get("/executions/nonexistent/lineage")
    assert response.status_code == 404


def test_correlation_not_found(api_client):
    """Test 404 for non-existent correlation."""
    response = api_client.get("/executions/correlation/nonexistent")
    assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
