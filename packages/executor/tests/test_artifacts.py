"""
Tests for Phase 2.2-A: Artifact Management

Validates:
- Artifact directory structure creation
- plan.json / changeset.json / decision.json / execution.json writing
- Step log append-only behavior
- Backup linking
- Execution replay from artifacts
- Retention and cleanup policies
"""

import pytest
import tempfile
import json
from pathlib import Path
from datetime import datetime, timedelta
import time

# Import executor components
from executor import (
    HostExecutor,
    ArtifactManager,
    ArtifactConfig,
    replay_execution
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
def artifact_manager(temp_workspace):
    """Create ArtifactManager instance."""
    return ArtifactManager(temp_workspace)


@pytest.fixture
def sample_plan():
    """Create sample ChangePlan."""
    return ChangePlan(
        id=generate_plan_id(),
        intent="Test plan",
        objective="Test artifact storage",
        rationale="Testing",
        affected_paths=["test.txt"],
        risk_level_proposed=RiskLevel.LOW,
        rollback_plan="rm test.txt",
        verification_plan="echo 'ok'",
        created_by="test",
        created_at=datetime.utcnow(),
        confidence=0.9
    )


@pytest.fixture
def sample_changeset(sample_plan):
    """Create sample ChangeSet."""
    change = FileChange(
        operation=Operation.CREATE,
        path="test.txt",
        new_content="Test content"
    )

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id=sample_plan.id,
        changes=[change],
        checksum="",
        generated_by="test",
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()
    return changeset


@pytest.fixture
def sample_decision(sample_plan, sample_changeset):
    """Create sample GovernanceDecision."""
    return GovernanceDecision(
        id=generate_decision_id(),
        plan_id=sample_plan.id,
        changeset_id=sample_changeset.id,
        verdict=Verdict.ALLOW,
        reasons=[],
        risk_level_effective=RiskLevel.LOW,
        policy_snapshot_hash="test_hash",
        agent_source_hash="test_hash",
        writegate_version="1.0.0",
        evaluated_at=datetime.utcnow(),
        evaluator="test"
    )


# ========== Test 1: Artifact Directory Creation ==========

def test_artifact_directory_creation(artifact_manager):
    """Test artifact directory structure is created correctly."""
    exec_id = "exec_test123"

    # Create execution directory
    exec_dir = artifact_manager.create_execution_dir(exec_id)

    # Validate structure
    assert exec_dir.exists()
    assert (exec_dir / "steps").exists()
    assert (exec_dir / "backups").exists()
    assert (exec_dir / "stdout.log").exists()
    assert (exec_dir / "stderr.log").exists()

    print(f"[OK] Artifact directory created: {exec_dir}")


# ========== Test 2: JSON Writing ==========

def test_json_artifact_writing(artifact_manager, sample_plan, sample_changeset, sample_decision):
    """Test plan/changeset/decision JSON files are written correctly."""
    exec_id = "exec_test456"

    # Create directory
    artifact_manager.create_execution_dir(exec_id)

    # Write JSONs
    plan_file = artifact_manager.write_plan(exec_id, sample_plan)
    changeset_file = artifact_manager.write_changeset(exec_id, sample_changeset)
    decision_file = artifact_manager.write_decision(exec_id, sample_decision)

    # Validate files exist
    assert plan_file.exists()
    assert changeset_file.exists()
    assert decision_file.exists()

    # Validate JSON content
    with open(plan_file, 'r', encoding='utf-8') as f:
        plan_data = json.load(f)
        assert plan_data['intent'] == "Test plan"
        assert plan_data['id'] == sample_plan.id

    with open(changeset_file, 'r', encoding='utf-8') as f:
        changeset_data = json.load(f)
        assert changeset_data['id'] == sample_changeset.id
        assert len(changeset_data['changes']) == 1

    with open(decision_file, 'r', encoding='utf-8') as f:
        decision_data = json.load(f)
        assert decision_data['verdict'] == 'allow'

    print(f"[OK] All JSON files written correctly")


# ========== Test 3: Step Log Append-Only ==========

def test_step_log_append_only(artifact_manager):
    """Test step logs are append-only."""
    exec_id = "exec_test789"

    # Create directory
    artifact_manager.create_execution_dir(exec_id)

    # Append multiple log entries
    artifact_manager.append_step_log(exec_id, 1, "validate", "Starting validation")
    artifact_manager.append_step_log(exec_id, 1, "validate", "Validation passed")
    artifact_manager.append_step_log(exec_id, 2, "apply", "Applying changes")

    # Read step logs
    step1_file = artifact_manager.base_dir / exec_id / "steps" / "01_validate.log"
    step2_file = artifact_manager.base_dir / exec_id / "steps" / "02_apply.log"

    assert step1_file.exists()
    assert step2_file.exists()

    # Validate step 1 has both entries
    step1_content = step1_file.read_text(encoding='utf-8')
    assert "Starting validation" in step1_content
    assert "Validation passed" in step1_content
    assert step1_content.count('\n') == 2  # Two log lines

    # Validate step 2 has one entry
    step2_content = step2_file.read_text(encoding='utf-8')
    assert "Applying changes" in step2_content

    print(f"[OK] Step logs are append-only")


# ========== Test 4: Execution Replay ==========

def test_execution_replay(artifact_manager, sample_plan, sample_changeset, sample_decision):
    """Test execution can be replayed from artifacts."""
    exec_id = "exec_test_replay"

    # Create artifacts
    artifact_manager.create_execution_dir(exec_id)
    artifact_manager.write_plan(exec_id, sample_plan)
    artifact_manager.write_changeset(exec_id, sample_changeset)
    artifact_manager.write_decision(exec_id, sample_decision)

    # Write execution result
    execution_result = {
        "execution_id": exec_id,
        "plan_id": sample_plan.id,
        "success": True,
        "message": "Test execution",
        "files_changed": 1,
        "duration_seconds": 1.5
    }
    artifact_manager.write_execution(exec_id, execution_result)

    # Write step logs
    artifact_manager.append_step_log(exec_id, 1, "validate", "Validated")
    artifact_manager.append_step_log(exec_id, 2, "apply", "Applied")

    # Replay execution
    exec_dir = artifact_manager.get_execution_dir(exec_id)
    replayed = replay_execution(exec_dir)

    # Validate replayed data
    assert replayed['plan']['intent'] == "Test plan"
    assert replayed['changeset']['id'] == sample_changeset.id
    assert replayed['decision']['verdict'] == 'allow'
    assert replayed['execution']['success'] is True
    assert len(replayed['step_logs']) == 2
    assert '01_validate' in replayed['step_logs']
    assert '02_apply' in replayed['step_logs']

    print(f"[OK] Execution replayed successfully from artifacts")


# ========== Test 5: Retention and Cleanup ==========

def test_artifact_cleanup_retention(temp_workspace):
    """Test artifact cleanup respects retention policy."""
    # Create artifact manager with short retention
    config = ArtifactConfig(
        retention_days=0,  # Expire immediately
        retention_count=2,  # Keep only 2 executions
        cleanup_strategy="lru"
    )
    manager = ArtifactManager(temp_workspace, config)

    # Create 5 executions
    exec_ids = []
    for i in range(5):
        exec_id = f"exec_test_{i}"
        exec_ids.append(exec_id)
        manager.create_execution_dir(exec_id)
        time.sleep(0.01)  # Ensure different mtimes

    # List all executions
    all_execs = manager.list_executions()
    assert len(all_execs) == 5

    # Run cleanup (should keep last 2)
    removed = manager.cleanup_old_artifacts()

    # Validate: 3 removed, 2 kept
    assert removed == 3
    remaining = manager.list_executions()
    assert len(remaining) == 2

    # Validate kept executions are the newest
    assert "exec_test_4" in remaining
    assert "exec_test_3" in remaining

    print(f"[OK] Cleanup removed {removed} artifacts, kept {len(remaining)}")


# ========== Test 6: End-to-End with Executor ==========

def test_end_to_end_artifact_integration(temp_workspace, sample_plan, sample_changeset, sample_decision):
    """Test artifacts are created during real execution."""
    executor = HostExecutor(temp_workspace)

    # Execute changeset
    result = executor.execute(sample_plan, sample_changeset, sample_decision)

    # Validate execution succeeded
    assert result.success is True

    # Validate artifacts were created
    exec_id = result.context.id
    artifact_dir = executor.artifact_manager.get_execution_dir(exec_id)

    assert artifact_dir is not None
    assert (artifact_dir / "plan.json").exists()
    assert (artifact_dir / "changeset.json").exists()
    assert (artifact_dir / "decision.json").exists()
    assert (artifact_dir / "execution.json").exists()

    # Validate step logs exist
    steps_dir = artifact_dir / "steps"
    assert steps_dir.exists()
    assert len(list(steps_dir.glob("*.log"))) > 0

    # Replay and validate
    replayed = replay_execution(artifact_dir)
    assert replayed['plan']['id'] == sample_plan.id
    assert replayed['execution']['success'] is True

    print(f"[OK] End-to-end artifact integration verified")


# ========== Run All Tests ==========

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
