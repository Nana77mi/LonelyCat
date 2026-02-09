"""
Tests for Host Executor - Phase 2

Validates:
- Executor workflow
- File application (CREATE/UPDATE/DELETE)
- Verification running
- Rollback on failure
- Health checks
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from executor import (
    HostExecutor,
    ExecutionStatus,
    FileApplier
)

# Import governance and planner
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from governance import (
    ChangePlan,
    ChangeSet,
    FileChange,
    Operation,
    RiskLevel,
    GovernanceDecision,
    Verdict,
    generate_plan_id,
    generate_changeset_id,
    generate_decision_id
)


@pytest.fixture
def temp_workspace():
    """Create temporary workspace for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def approved_decision():
    """Create an approved GovernanceDecision."""
    return GovernanceDecision(
        id=generate_decision_id(),
        plan_id="test_plan",
        changeset_id="test_changeset",
        verdict=Verdict.ALLOW,
        reasons=[],
        risk_level_effective=RiskLevel.LOW,
        policy_snapshot_hash="test_hash",
        agent_source_hash="test_hash",
        writegate_version="1.0.0",
        evaluated_at=datetime.utcnow(),
        evaluator="test"
    )


# ==================== File Applier Tests ====================

def test_file_applier_create(temp_workspace):
    """Test creating a new file."""
    applier = FileApplier(temp_workspace)

    change = FileChange(
        operation=Operation.CREATE,
        path="test.txt",
        new_content="Hello World"
    )

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id="test",
        changes=[change],
        checksum="",
        generated_by="test",
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()

    applied = applier.apply_changeset(changeset)

    assert len(applied) == 1
    assert "test.txt" in applied[0]

    # Verify file was created
    test_file = temp_workspace / "test.txt"
    assert test_file.exists()
    assert test_file.read_text() == "Hello World"


def test_file_applier_update(temp_workspace):
    """Test updating an existing file."""
    # Create initial file
    test_file = temp_workspace / "test.txt"
    test_file.write_text("Old content")

    applier = FileApplier(temp_workspace)

    change = FileChange(
        operation=Operation.UPDATE,
        path="test.txt",
        old_content="Old content",
        new_content="New content"
    )

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id="test",
        changes=[change],
        checksum="",
        generated_by="test",
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()

    applied = applier.apply_changeset(changeset)

    assert len(applied) == 1

    # Verify file was updated
    assert test_file.read_text() == "New content"


def test_file_applier_delete(temp_workspace):
    """Test deleting a file."""
    # Create initial file
    test_file = temp_workspace / "test.txt"
    test_file.write_text("Content to delete")

    applier = FileApplier(temp_workspace)

    change = FileChange(
        operation=Operation.DELETE,
        path="test.txt",
        old_content="Content to delete"
    )

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id="test",
        changes=[change],
        checksum="",
        generated_by="test",
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()

    applied = applier.apply_changeset(changeset)

    assert len(applied) == 1

    # Verify file was deleted
    assert not test_file.exists()


# ==================== Executor Tests ====================

def test_executor_validates_approval(temp_workspace, approved_decision):
    """Test executor validates approval before execution."""
    executor = HostExecutor(temp_workspace)

    # Create denied decision
    denied_decision = GovernanceDecision(
        id=generate_decision_id(),
        plan_id="test",
        changeset_id="test",
        verdict=Verdict.DENY,
        reasons=["Test denial"],
        risk_level_effective=RiskLevel.HIGH,
        policy_snapshot_hash="test",
        agent_source_hash="test",
        writegate_version="1.0.0",
        evaluated_at=datetime.utcnow(),
        evaluator="test"
    )

    plan = ChangePlan(
        id=generate_plan_id(),
        intent="Test",
        objective="Test",
        rationale="Test",
        affected_paths=["test.txt"],
        risk_level_proposed=RiskLevel.LOW,
        rollback_plan="Test rollback",
        verification_plan="echo 'verified'",
        created_by="test",
        created_at=datetime.utcnow(),
        confidence=0.9
    )

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id=plan.id,
        changes=[],
        checksum="",
        generated_by="test",
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()

    # Should fail with denied decision
    result = executor.execute(plan, changeset, denied_decision)

    assert result.success is False
    assert "verdict is deny" in result.message.lower()


def test_executor_full_workflow_success(temp_workspace, approved_decision):
    """Test complete successful execution workflow."""
    executor = HostExecutor(temp_workspace)

    # Create plan
    plan = ChangePlan(
        id=generate_plan_id(),
        intent="Create test file",
        objective="Test executor",
        rationale="Testing",
        affected_paths=["test.txt"],
        risk_level_proposed=RiskLevel.LOW,
        rollback_plan="rm test.txt",
        verification_plan="echo 'verified'",  # Simple verification
        created_by="test",
        created_at=datetime.utcnow(),
        confidence=0.9
    )

    # Create changeset
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
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()

    # Update decision IDs to match
    approved_decision.plan_id = plan.id
    approved_decision.changeset_id = changeset.id

    # Execute
    result = executor.execute(plan, changeset, approved_decision)

    # Should succeed
    assert result.success is True
    assert result.context.status == ExecutionStatus.COMPLETED
    assert result.files_changed == 1
    assert result.verification_passed is True

    # Verify file was created
    test_file = temp_workspace / "test.txt"
    assert test_file.exists()
    assert test_file.read_text() == "Test content"


def test_executor_rollback_on_failure(temp_workspace, approved_decision):
    """Test executor rolls back changes on failure."""
    executor = HostExecutor(temp_workspace)

    # Create initial file
    test_file = temp_workspace / "test.txt"
    test_file.write_text("Original content")

    # Create plan
    plan = ChangePlan(
        id=generate_plan_id(),
        intent="Update file",
        objective="Test rollback",
        rationale="Testing",
        affected_paths=["test.txt"],
        risk_level_proposed=RiskLevel.LOW,
        rollback_plan="Restore backup",
        verification_plan="exit 1",  # Force verification failure
        created_by="test",
        created_at=datetime.utcnow(),
        confidence=0.9
    )

    # Create changeset
    change = FileChange(
        operation=Operation.UPDATE,
        path="test.txt",
        old_content="Original content",
        new_content="Modified content"
    )

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id=plan.id,
        changes=[change],
        checksum="",
        generated_by="test",
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()

    approved_decision.plan_id = plan.id
    approved_decision.changeset_id = changeset.id

    # Execute (should fail verification and rollback)
    result = executor.execute(plan, changeset, approved_decision)

    # Should fail
    assert result.success is False
    assert result.context.status == ExecutionStatus.ROLLED_BACK
    assert result.context.rolled_back is True

    # File should be restored to original content
    assert test_file.read_text() == "Original content"


def test_executor_dry_run(temp_workspace, approved_decision):
    """Test executor dry-run mode."""
    executor = HostExecutor(temp_workspace, dry_run=True)

    plan = ChangePlan(
        id=generate_plan_id(),
        intent="Test dry run",
        objective="Test",
        rationale="Test",
        affected_paths=["test.txt"],
        risk_level_proposed=RiskLevel.LOW,
        rollback_plan="Test",
        verification_plan="Test",
        created_by="test",
        created_at=datetime.utcnow(),
        confidence=0.9
    )

    change = FileChange(
        operation=Operation.CREATE,
        path="test.txt",
        new_content="Should not be created"
    )

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id=plan.id,
        changes=[change],
        checksum="",
        generated_by="test",
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()

    approved_decision.plan_id = plan.id
    approved_decision.changeset_id = changeset.id

    # Execute in dry-run
    result = executor.execute(plan, changeset, approved_decision)

    # Should succeed (dry run)
    assert result.success is True

    # File should NOT be created
    test_file = temp_workspace / "test.txt"
    assert not test_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
