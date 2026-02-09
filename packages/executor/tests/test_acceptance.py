"""
Phase 2 Acceptance Tests - Production-like validation

These tests validate the system under conditions closer to production
than unit tests. They test the 5 critical scenarios identified for
Phase 2 stability.

Test Scenarios:
1. Concurrent writes - must serialize or reject
2. Duplicate submission - must be idempotent
3. Partial failure rollback - first step must recover
4. Checksum tampering - must reject
5. Path boundary violation - double defense (WriteGate + Executor)
"""

import pytest
import tempfile
import threading
import time
from pathlib import Path
from datetime import datetime

# Import executor components
from executor import (
    HostExecutor,
    ExecutionLock,
    LockManager,
    LockAcquisitionError,
    IdempotencyManager,
    ExecutionStatus
)

# Import governance
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
    WriteGate,
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


# ========== Acceptance Test 1: Concurrent Writes ==========

def test_concurrent_writes_must_serialize(temp_workspace, approved_decision):
    """
    ACCEPTANCE TEST 1: Concurrent Writes

    Scenario: Two ChangeSets attempt to execute simultaneously
    Expected: Lock enforces serialization (A completes before B starts)

    This verifies:
    - 互斥性 (Mutual Exclusion): Max 1 in _do_execute at any time
    - 顺序性 (Serialization): B's start >= A's end
    - 无副作用冲突 (No Corruption): Files/backups consistent

    Strategy: Use hooks + threading.Event for deterministic testing
    """
    # Events for precise control
    entered_A = threading.Event()
    block_A = threading.Event()
    entered_B = threading.Event()
    finished_A = threading.Event()
    finished_B = threading.Event()

    # Track concurrent execution (should never happen)
    concurrent_execution = threading.Event()
    inside_execute = threading.Lock()

    def before_hook(exec_id, plan_id):
        """Called when entering _do_execute"""
        # Try to acquire - if fails, means concurrent execution
        if not inside_execute.acquire(blocking=False):
            concurrent_execution.set()  # VIOLATION
            return

        if plan_id == "plan_A":
            entered_A.set()
            block_A.wait()  # Block A until test releases
        elif plan_id == "plan_B":
            entered_B.set()

    def after_hook(exec_id, plan_id):
        """Called when exiting _do_execute"""
        if plan_id == "plan_A":
            finished_A.set()
        elif plan_id == "plan_B":
            finished_B.set()

        inside_execute.release()

    # Create executor with hooks
    executor = HostExecutor(
        temp_workspace,
        use_locking=True,
        use_idempotency=False,  # Disable for speed
        hooks={
            "before_do_execute": before_hook,
            "after_do_execute": after_hook
        }
    )

    # Create two simple changesets
    results = [None, None]

    def execute_A():
        plan = ChangePlan(
            id="plan_A",
            intent="Test A",
            objective="Test",
            rationale="Test",
            affected_paths=["test_A.txt"],
            risk_level_proposed=RiskLevel.LOW,
            rollback_plan="rm test_A.txt",
            verification_plan="echo 'ok'",  # Fast verification
            created_by="test",
            created_at=datetime.utcnow(),
            confidence=0.9
        )

        change = FileChange(
            operation=Operation.CREATE,
            path="test_A.txt",
            new_content="Content A"
        )

        changeset = ChangeSet(
            id="changeset_A",
            plan_id=plan.id,
            changes=[change],
            checksum="",
            generated_by="test",
            generated_at=datetime.utcnow()
        )
        changeset.compute_checksum()

        approved_decision.plan_id = plan.id
        approved_decision.changeset_id = changeset.id

        results[0] = executor.execute(plan, changeset, approved_decision)

    def execute_B():
        plan = ChangePlan(
            id="plan_B",
            intent="Test B",
            objective="Test",
            rationale="Test",
            affected_paths=["test_B.txt"],
            risk_level_proposed=RiskLevel.LOW,
            rollback_plan="rm test_B.txt",
            verification_plan="echo 'ok'",
            created_by="test",
            created_at=datetime.utcnow(),
            confidence=0.9
        )

        change = FileChange(
            operation=Operation.CREATE,
            path="test_B.txt",
            new_content="Content B"
        )

        changeset = ChangeSet(
            id="changeset_B",
            plan_id=plan.id,
            changes=[change],
            checksum="",
            generated_by="test",
            generated_at=datetime.utcnow()
        )
        changeset.compute_checksum()

        approved_decision.plan_id = plan.id
        approved_decision.changeset_id = changeset.id

        results[1] = executor.execute(plan, changeset, approved_decision)

    # Start thread A
    thread_A = threading.Thread(target=execute_A)
    thread_A.start()

    # Wait for A to enter _do_execute
    assert entered_A.wait(timeout=5), "Thread A should enter execution"

    # Start thread B (should block on lock acquisition)
    thread_B = threading.Thread(target=execute_B)
    thread_B.start()

    # Give B time to try acquiring lock
    time.sleep(0.2)

    # VALIDATE 1: B should NOT have entered yet (lock blocking)
    assert not entered_B.is_set(), "Thread B should be blocked by lock while A is executing"

    # Release A
    block_A.set()

    # Wait for A to finish
    assert finished_A.wait(timeout=10), "Thread A should finish execution"

    # Now B should be able to proceed
    assert entered_B.wait(timeout=10), "Thread B should enter after A releases lock"
    assert finished_B.wait(timeout=10), "Thread B should finish execution"

    # Wait for threads to complete
    thread_A.join(timeout=15)
    thread_B.join(timeout=15)

    # VALIDATE 2: No concurrent execution detected
    assert not concurrent_execution.is_set(), \
        "Concurrent execution detected - lock did not enforce mutual exclusion"

    # VALIDATE 3: Both executions succeeded
    assert results[0] is not None and results[0].success, "Thread A execution should succeed"
    assert results[1] is not None and results[1].success, "Thread B execution should succeed"

    # VALIDATE 4: No file corruption
    file_A = temp_workspace / "test_A.txt"
    file_B = temp_workspace / "test_B.txt"
    assert file_A.exists() and file_A.read_text() == "Content A", "File A should be created correctly"
    assert file_B.exists() and file_B.read_text() == "Content B", "File B should be created correctly"

    print(f"[OK] Serialization verified: A completed before B started, no concurrent execution")


# ========== Acceptance Test 2: Duplicate Submission ==========

def test_duplicate_submission_is_idempotent(temp_workspace, approved_decision):
    """
    ACCEPTANCE TEST 2: Duplicate Submission

    Scenario: Same ChangeSet is submitted twice
    Expected: Second execution detects duplicate and returns cached result

    This prevents:
    - Duplicate file modifications
    - Wasted execution resources
    - Inconsistent state from repeated application
    """
    executor = HostExecutor(temp_workspace)
    idem_mgr = IdempotencyManager(temp_workspace, ttl_seconds=3600)

    # Create changeset
    plan = ChangePlan(
        id=generate_plan_id(),
        intent="Create test file",
        objective="Test idempotency",
        rationale="Test",
        affected_paths=["test.txt"],
        risk_level_proposed=RiskLevel.LOW,
        rollback_plan="rm test.txt",
        verification_plan="echo 'ok'",
        created_by="test",
        created_at=datetime.utcnow(),
        confidence=0.9
    )

    change = FileChange(
        operation=Operation.CREATE,
        path="test.txt",
        new_content="Original content"
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

    # FIRST EXECUTION
    from executor.idempotency import IdempotencyCheck

    with IdempotencyCheck(idem_mgr, plan.id, changeset.checksum) as check:
        # Should not be already executed
        assert not check.already_executed, "First execution should not be marked as duplicate"

        # Execute
        result1 = executor.execute(plan, changeset, approved_decision)
        assert result1.success, "First execution should succeed"

        # Record result
        check.record_result(
            changeset_id=changeset.id,
            status="completed",
            files_changed=1,
            verification_passed=True,
            message="Success"
        )

    # SECOND EXECUTION (DUPLICATE)
    with IdempotencyCheck(idem_mgr, plan.id, changeset.checksum) as check:
        # Should detect duplicate
        assert check.already_executed, "Second execution should detect duplicate"
        assert check.previous_record is not None, "Should have previous execution record"

        # VALIDATE: Previous execution was successful
        assert check.previous_record.status == "completed"
        assert check.previous_record.verification_passed is True

        # Should NOT execute again
        print(f"Duplicate detected: {check.previous_record.message}")

    # VALIDATE: File was created only once
    test_file = temp_workspace / "test.txt"
    assert test_file.exists(), "File should exist from first execution"
    assert test_file.read_text() == "Original content"


# ========== Acceptance Test 3: Partial Failure Rollback ==========

def test_partial_failure_triggers_complete_rollback(temp_workspace, approved_decision):
    """
    ACCEPTANCE TEST 3: Partial Failure Rollback

    Scenario: Step 2 fails after Step 1 succeeds
    Expected: Step 1 must be rolled back (all or nothing)

    This prevents:
    - Partial state from failed executions
    - Drift between intended and actual state
    - Manual cleanup burden
    """
    executor = HostExecutor(temp_workspace)

    # Create initial file (will be updated)
    test_file = temp_workspace / "test.txt"
    test_file.write_text("Original content")

    # Create plan that will fail verification
    plan = ChangePlan(
        id=generate_plan_id(),
        intent="Update file (will fail)",
        objective="Test rollback",
        rationale="Test",
        affected_paths=["test.txt"],
        risk_level_proposed=RiskLevel.LOW,
        rollback_plan="Restore backup",
        verification_plan="exit 1",  # FORCE FAILURE
        created_by="test",
        created_at=datetime.utcnow(),
        confidence=0.9
    )

    # Change will modify file
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

    # EXECUTE (will fail at verification step)
    result = executor.execute(plan, changeset, approved_decision)

    # VALIDATE: Execution failed
    assert result.success is False, "Execution should fail due to verification"
    assert result.context.status == ExecutionStatus.ROLLED_BACK, "Should be rolled back"
    assert result.context.rolled_back is True, "Rollback flag should be set"

    # CRITICAL: File must be restored to original content
    current_content = test_file.read_text()
    assert current_content == "Original content", \
        f"File should be rolled back to original, got: {current_content}"

    print(f"[OK] Rollback successful: {result.message}")


# ========== Acceptance Test 4: Checksum Tampering ==========

def test_checksum_tampering_is_rejected(temp_workspace, approved_decision):
    """
    ACCEPTANCE TEST 4: Checksum Tampering

    Scenario: ChangeSet checksum does not match content
    Expected: Execution must reject (security violation)

    This prevents:
    - Execution of tampered ChangeSets
    - Unauthorized modifications
    - Bypassing WriteGate approval
    """
    executor = HostExecutor(temp_workspace)

    # Create valid changeset
    plan = ChangePlan(
        id=generate_plan_id(),
        intent="Create file",
        objective="Test",
        rationale="Test",
        affected_paths=["test.txt"],
        risk_level_proposed=RiskLevel.LOW,
        rollback_plan="Test",
        verification_plan="echo 'ok'",
        created_by="test",
        created_at=datetime.utcnow(),
        confidence=0.9
    )

    change = FileChange(
        operation=Operation.CREATE,
        path="test.txt",
        new_content="Original content"
    )

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id=plan.id,
        changes=[change],
        checksum="",
        generated_by="test",
        generated_at=datetime.utcnow()
    )

    # Compute correct checksum
    changeset.compute_checksum()
    original_checksum = changeset.checksum

    # TAMPER: Modify content without updating checksum
    changeset.changes[0].new_content = "TAMPERED CONTENT"
    # Checksum is now invalid!

    approved_decision.plan_id = plan.id
    approved_decision.changeset_id = changeset.id

    # EXECUTE (should reject)
    result = executor.execute(plan, changeset, approved_decision)

    # VALIDATE: Execution rejected
    assert result.success is False, "Tampered ChangeSet should be rejected"
    assert "checksum" in result.message.lower(), \
        f"Error should mention checksum, got: {result.message}"

    # VALIDATE: No file was created
    test_file = temp_workspace / "test.txt"
    assert not test_file.exists(), "Tampered execution should not create files"

    print(f"[OK] Tampering detected: {result.message}")


# ========== Acceptance Test 5: Path Boundary Violation ==========

def test_path_boundary_violation_double_defense(temp_workspace):
    """
    ACCEPTANCE TEST 5: Path Boundary Violation

    Scenario: Attempt to write to forbidden path
    Expected: WriteGate DENY + Executor also rejects (double defense)

    This prevents:
    - Modification of critical system files
    - Accidental .git corruption
    - Secret leakage
    """
    writegate = WriteGate()
    executor = HostExecutor(temp_workspace)

    # Create plan that tries to modify forbidden path
    plan = ChangePlan(
        id=generate_plan_id(),
        intent="Modify .env (FORBIDDEN)",
        objective="Test boundary",
        rationale="Test",
        affected_paths=[".env"],  # FORBIDDEN PATH
        risk_level_proposed=RiskLevel.LOW,  # Agent lies about risk
        rollback_plan="Test",
        verification_plan="Test",
        created_by="test",
        created_at=datetime.utcnow(),
        confidence=0.9
    )

    change = FileChange(
        operation=Operation.CREATE,
        path=".env",
        new_content="SECRET_KEY=hacked"
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

    # DEFENSE 1: WriteGate should DENY
    decision = writegate.evaluate(plan, changeset)

    assert decision.verdict == Verdict.DENY, \
        f"WriteGate should DENY forbidden path, got: {decision.verdict}"
    assert any("forbidden" in r.lower() for r in decision.reasons), \
        f"Denial reason should mention forbidden path, got: {decision.reasons}"

    print(f"[OK] WriteGate blocked: {decision.reasons}")

    # DEFENSE 2: Even if Executor called directly (shouldn't happen)
    # Executor validates decision verdict
    result = executor.execute(plan, changeset, decision)

    assert result.success is False, "Executor should also reject DENY verdict"
    assert "deny" in result.message.lower(), \
        f"Error should mention denial, got: {result.message}"

    # VALIDATE: No file was created
    test_file = temp_workspace / ".env"
    assert not test_file.exists(), "Forbidden file should not be created"

    print(f"[OK] Executor double-defense: {result.message}")


# ========== Run All Acceptance Tests ==========

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
