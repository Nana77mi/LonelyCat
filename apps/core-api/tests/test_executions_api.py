"""
Tests for Execution History API - Phase 2.3-A

Validates:
- GET /executions - List with filters
- GET /executions/{id} - Get details with steps
- GET /executions/{id}/artifacts - Get artifact metadata
- GET /executions/{id}/replay - Replay execution
- Security boundaries (path whitelist)
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from fastapi.testclient import TestClient

# Import app
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app
from app.api.executions import WORKSPACE_ROOT, execution_store

# Import test utilities
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "packages"))

from governance import (
    ChangePlan,
    ChangeSet,
    FileChange,
    Operation,
    RiskLevel,
    Verdict,
    GovernanceDecision,
    generate_plan_id,
    generate_changeset_id,
    generate_decision_id
)

from executor import HostExecutor


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def temp_workspace():
    """Create temporary workspace for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_execution():
    """Create a sample execution for testing."""
    # Use API's WORKSPACE_ROOT instead of temp workspace
    # so the execution can be found by the API
    from app.api.executions import WORKSPACE_ROOT

    # Create sample plan
    plan = ChangePlan(
        id=generate_plan_id(),
        intent="Test execution",
        objective="Test API",
        rationale="Testing",
        affected_paths=["test.txt"],
        risk_level_proposed=RiskLevel.LOW,
        rollback_plan="rm test.txt",
        verification_plan="echo ok",
        created_by="test",
        created_at=datetime.now(timezone.utc),
        confidence=0.9
    )

    # Create sample changeset
    change = FileChange(
        operation=Operation.CREATE,
        path="test.txt",
        new_content="Test content"
    )

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id=plan.id,
        changes=[change],
        checksum="",
        generated_by="test",
        generated_at=datetime.now(timezone.utc)
    )
    changeset.compute_checksum()

    # Create sample decision
    decision = GovernanceDecision(
        id=generate_decision_id(),
        plan_id=plan.id,
        changeset_id=changeset.id,
        verdict=Verdict.ALLOW,
        reasons=[],
        risk_level_effective=RiskLevel.LOW,
        policy_snapshot_hash="test_hash",
        agent_source_hash="test_hash",
        writegate_version="1.0.0",
        evaluated_at=datetime.now(timezone.utc),
        evaluator="test"
    )

    # Execute using WORKSPACE_ROOT
    executor = HostExecutor(WORKSPACE_ROOT)
    result = executor.execute(plan, changeset, decision)

    exec_id = result.context.id

    yield exec_id

    # Cleanup after test
    import shutil
    artifact_dir = WORKSPACE_ROOT / ".lonelycat" / "executions" / exec_id
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir, ignore_errors=True)

    # Note: SQLite record remains (no cleanup for MVP)
    # In production, you might want to add a cleanup method


# ========== Test 1: List Executions ==========

def test_list_executions(client):
    """Test GET /executions returns execution list."""
    response = client.get("/executions")

    assert response.status_code == 200
    data = response.json()

    assert "executions" in data
    assert "total" in data
    assert "limit" in data
    assert isinstance(data["executions"], list)

    print(f"[OK] Listed {data['total']} executions")


# ========== Test 2: List with Filters ==========

def test_list_executions_with_filters(client):
    """Test GET /executions with status filter."""
    response = client.get("/executions?status=completed&limit=5")

    assert response.status_code == 200
    data = response.json()

    assert data["limit"] == 5
    # All returned executions should have status=completed (if any exist)
    for exec in data["executions"]:
        if exec["status"]:  # May be empty list
            assert exec["status"] == "completed"

    print(f"[OK] Filtered by status=completed, got {len(data['executions'])} results")


# ========== Test 3: Get Execution Details ==========

def test_get_execution_details(client, sample_execution):
    """Test GET /executions/{id} returns execution details with steps."""
    response = client.get(f"/executions/{sample_execution}")

    assert response.status_code == 200
    data = response.json()

    assert "execution" in data
    assert "steps" in data
    assert "artifact_path" in data

    exec_data = data["execution"]
    assert exec_data["execution_id"] == sample_execution
    assert "status" in exec_data
    assert "verdict" in exec_data

    print(f"[OK] Got execution {sample_execution} with {len(data['steps'])} steps")


# ========== Test 4: Get Non-Existent Execution ==========

def test_get_nonexistent_execution(client):
    """Test GET /executions/{id} returns 404 for non-existent ID."""
    response = client.get("/executions/exec_nonexistent123")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

    print("[OK] 404 for non-existent execution")


# ========== Test 5: Get Artifacts Metadata ==========

def test_get_artifacts_metadata(client, sample_execution):
    """Test GET /executions/{id}/artifacts returns artifact metadata."""
    response = client.get(f"/executions/{sample_execution}/artifacts")

    assert response.status_code == 200
    data = response.json()

    assert "artifact_path" in data
    assert "artifacts_complete" in data
    assert "four_piece_set" in data
    assert "step_logs" in data
    assert "has_stdout" in data
    assert "has_stderr" in data

    # Check 4件套
    four_piece = data["four_piece_set"]
    assert "plan.json" in four_piece
    assert "changeset.json" in four_piece
    assert "decision.json" in four_piece
    assert "execution.json" in four_piece

    print(f"[OK] Artifacts complete: {data['artifacts_complete']}, logs: {len(data['step_logs'])}")


# ========== Test 6: Replay Execution ==========

def test_replay_execution(client, sample_execution):
    """Test GET /executions/{id}/replay returns execution replay summary."""
    response = client.get(f"/executions/{sample_execution}/replay")

    assert response.status_code == 200
    data = response.json()

    assert "execution_id" in data
    assert data["execution_id"] == sample_execution
    assert "plan" in data
    assert "changeset" in data
    assert "decision" in data
    assert "execution" in data

    # Check structure
    assert "intent" in data["plan"]
    assert "verdict" in data["decision"]
    assert "status" in data["execution"]

    print(f"[OK] Replayed execution {sample_execution}")


# ========== Test 7: Security - Path Whitelist ==========

def test_security_path_whitelist():
    """Test artifact path validation (security boundary)."""
    from app.api.executions import validate_artifact_path

    # Valid paths
    valid_path = WORKSPACE_ROOT / ".lonelycat" / "executions" / "exec_123"
    assert validate_artifact_path(valid_path) is True

    # Invalid paths (outside executions/)
    invalid_path1 = WORKSPACE_ROOT / ".lonelycat" / "other"
    assert validate_artifact_path(invalid_path1) is False

    invalid_path2 = WORKSPACE_ROOT / "packages"
    assert validate_artifact_path(invalid_path2) is False

    # Path traversal attempt
    traversal_path = WORKSPACE_ROOT / ".lonelycat" / "executions" / ".." / ".." / "packages"
    assert validate_artifact_path(traversal_path) is False

    print("[OK] Path whitelist security working")


# ========== Test 8: Statistics Endpoint ==========

def test_get_statistics(client):
    """Test GET /executions/statistics returns aggregated metrics."""
    response = client.get("/executions/statistics")

    assert response.status_code == 200
    data = response.json()

    assert "total_executions" in data
    assert "by_status" in data
    assert isinstance(data["by_status"], dict)

    print(f"[OK] Statistics: {data['total_executions']} total executions")


# ========== Test 9: Pagination ==========

def test_pagination(client):
    """Test pagination with limit and offset."""
    # Get first page
    response1 = client.get("/executions?limit=2&offset=0")
    assert response1.status_code == 200
    data1 = response1.json()

    # Get second page
    response2 = client.get("/executions?limit=2&offset=2")
    assert response2.status_code == 200
    data2 = response2.json()

    # If we have enough executions, pages should be different
    if len(data1["executions"]) == 2 and len(data2["executions"]) > 0:
        exec_ids_1 = [e["execution_id"] for e in data1["executions"]]
        exec_ids_2 = [e["execution_id"] for e in data2["executions"]]
        # Pages should not overlap
        assert set(exec_ids_1).isdisjoint(set(exec_ids_2))

    print(f"[OK] Pagination working: page1={len(data1['executions'])}, page2={len(data2['executions'])}")


# ========== Run All Tests ==========

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
