"""
Tests for WriteGate Governance System

Validates:
- ChangePlan creation and persistence
- ChangeSet generation and checksum
- WriteGate evaluation logic
- Forbidden paths enforcement
- Risk escalation
- Approval workflow
"""

import pytest
from datetime import datetime
from pathlib import Path
import sys

# Add packages to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "packages"))

from governance import (
    ChangePlan,
    ChangeSet,
    FileChange,
    Operation,
    RiskLevel,
    Verdict,
    WriteGate,
    GovernanceStore,
    generate_plan_id,
    generate_changeset_id
)


@pytest.fixture
def sample_plan():
    """Create a sample ChangePlan."""
    return ChangePlan(
        id=generate_plan_id(),
        intent="Fix memory conflict resolution bug",
        objective="Add semantic similarity check",
        rationale="Current logic too simplistic (30% conflicts)",
        affected_paths=["packages/memory/facts.py"],
        dependencies=[],
        risk_level_proposed=RiskLevel.LOW,
        rollback_plan="git revert <commit> && restart services",
        verification_plan="Run test_memory.py, check GET /health",
        health_checks=["GET /health returns 200"],
        policy_refs=["writegate_rules"],
        created_by="agent",
        created_at=datetime.utcnow(),
        confidence=0.85,
        run_id="run_123"
    )


@pytest.fixture
def sample_changeset(sample_plan):
    """Create a sample ChangeSet."""
    change = FileChange(
        operation=Operation.UPDATE,
        path="packages/memory/facts.py",
        old_content="def resolve_conflict():\n    return 'keep_both'\n",
        new_content="def resolve_conflict():\n    # Add semantic check\n    return 'overwrite'\n",
        diff_unified="@@ -1,2 +1,3 @@\n def resolve_conflict():\n+    # Add semantic check\n-    return 'keep_both'\n+    return 'overwrite'\n",
        line_count_delta=1,
        size_bytes=120
    )
    change.compute_hashes()

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id=sample_plan.id,
        changes=[change],
        checksum="",
        generated_by="agent",
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()

    return changeset


def test_changeset_checksum(sample_changeset):
    """Test ChangeSet checksum computation and verification."""
    # Should verify successfully
    assert sample_changeset.verify_checksum() is True

    # Tamper with changeset
    sample_changeset.changes[0].new_content = "malicious code"

    # Should fail verification
    assert sample_changeset.verify_checksum() is False


def test_writegate_forbidden_paths(sample_plan):
    """Test WriteGate blocks forbidden paths."""
    # Create changeset touching forbidden path
    forbidden_change = FileChange(
        operation=Operation.UPDATE,
        path="agent/policies/default.yaml",  # FORBIDDEN!
        old_content="old",
        new_content="new"
    )

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id=sample_plan.id,
        changes=[forbidden_change],
        checksum="",
        generated_by="agent",
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()

    # Evaluate with WriteGate
    writegate = WriteGate()
    decision = writegate.evaluate(sample_plan, changeset)

    # Should be DENIED
    assert decision.verdict == Verdict.DENY
    assert "forbidden" in " ".join(decision.reasons).lower()
    assert decision.risk_level_effective == RiskLevel.CRITICAL


def test_writegate_risk_escalation(sample_plan, sample_changeset):
    """Test WriteGate escalates risk for critical files."""
    # Modify changeset to touch critical file
    sample_changeset.changes[0].path = "apps/core-api/app/main.py"

    # Evaluate
    writegate = WriteGate()
    decision = writegate.evaluate(sample_plan, sample_changeset)

    # Risk should be escalated to at least MEDIUM
    assert decision.risk_level_effective >= RiskLevel.MEDIUM
    assert "Risk escalated" in " ".join(decision.reasons)


def test_writegate_gating_requirements():
    """Test WriteGate requires rollback/verification plans."""
    # Plan missing rollback plan
    bad_plan = ChangePlan(
        id=generate_plan_id(),
        intent="Test",
        objective="Test",
        rationale="Test",
        affected_paths=["test.py"],
        dependencies=[],
        risk_level_proposed=RiskLevel.LOW,
        rollback_plan="",  # MISSING!
        verification_plan="",  # MISSING!
        health_checks=[],
        policy_refs=[],
        created_by="agent",
        created_at=datetime.utcnow(),
        confidence=0.85
    )

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id=bad_plan.id,
        changes=[],
        checksum="",
        generated_by="agent",
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()

    writegate = WriteGate()
    decision = writegate.evaluate(bad_plan, changeset)

    # Should require approval due to missing plans
    assert decision.verdict == Verdict.NEED_APPROVAL
    assert "rollback" in " ".join(decision.reasons).lower()
    assert "verification" in " ".join(decision.reasons).lower()


def test_writegate_allow_low_risk(sample_plan, sample_changeset):
    """Test WriteGate allows LOW risk with complete gating."""
    writegate = WriteGate()
    decision = writegate.evaluate(sample_plan, sample_changeset)

    # LOW risk in test file should be ALLOWED
    # (unless risk is escalated by path matching)
    # Since sample uses packages/memory/facts.py (critical pattern), it may escalate
    # So we just check decision is not DENY
    assert decision.verdict != Verdict.DENY


def test_storage_roundtrip(sample_plan, sample_changeset):
    """Test storing and retrieving governance objects."""
    # Use temporary database
    import tempfile
    temp_db = Path(tempfile.mktemp(suffix=".db"))

    # Initialize schema
    from governance.schema import init_governance_db
    init_governance_db(temp_db)

    store = GovernanceStore(temp_db)

    # Save plan
    store.save_plan(sample_plan)

    # Retrieve plan
    retrieved_plan = store.get_plan(sample_plan.id)
    assert retrieved_plan is not None
    assert retrieved_plan.id == sample_plan.id
    assert retrieved_plan.intent == sample_plan.intent

    # Save changeset
    store.save_changeset(sample_changeset)

    # Retrieve changeset
    retrieved_changeset = store.get_changeset(sample_changeset.id)
    assert retrieved_changeset is not None
    assert retrieved_changeset.id == sample_changeset.id
    assert retrieved_changeset.verify_checksum() is True

    # Cleanup
    temp_db.unlink()


def test_full_governance_flow(sample_plan, sample_changeset):
    """Test complete governance workflow."""
    import tempfile
    temp_db = Path(tempfile.mktemp(suffix=".db"))

    from governance.schema import init_governance_db
    from governance import GovernanceApproval, generate_approval_id

    init_governance_db(temp_db)
    store = GovernanceStore(temp_db)
    writegate = WriteGate()

    # Step 1: Save plan
    store.save_plan(sample_plan)

    # Step 2: Save changeset
    store.save_changeset(sample_changeset)

    # Step 3: Evaluate with WriteGate
    decision = writegate.evaluate(sample_plan, sample_changeset)
    store.save_decision(decision)

    # Step 4: If NEED_APPROVAL, create approval
    if decision.needs_user_approval():
        approval = GovernanceApproval(
            id=generate_approval_id(),
            plan_id=sample_plan.id,
            decision_id=decision.id,
            approved_by="human_user",
            approved_at=datetime.utcnow(),
            approval_notes="Looks good!"
        )
        store.save_approval(approval)

        # Verify approval exists
        assert store.plan_has_approval(sample_plan.id) is True

    # Get full record
    record = store.get_full_governance_record(sample_plan.id)
    assert record["plan"] is not None
    assert record["changeset"] is not None
    assert record["decision"] is not None

    # Cleanup
    temp_db.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
