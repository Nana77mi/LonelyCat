"""
Tests for Execution Graph (Phase 2.4-A)

Validates:
- Schema migration to add graph fields
- Execution lineage queries
- Correlation chain queries
- Graph traversal (ancestors/descendants)
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import sqlite3

# Add packages to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "packages"))

from executor.migrations import run_migrations, get_current_version, rollback_migration
from executor.storage import ExecutionStore, ExecutionRecord
from executor.schema import init_executor_db


@pytest.fixture
def temp_workspace():
    """Create temporary workspace with database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        yield workspace


# ========== Test 1: Migration System ==========

def test_migration_version_tracking(temp_workspace):
    """Test migration version tracking."""
    db_path = temp_workspace / ".lonelycat" / "executor.db"

    # Initialize database
    init_executor_db(db_path)

    # Check version
    conn = sqlite3.connect(db_path)
    version = get_current_version(conn)
    conn.close()

    # Should be at version 1 (execution graph migration)
    assert version == 1

    print(f"[OK] Migration version: {version}")


def test_migration_adds_graph_fields(temp_workspace):
    """Test that migration adds graph fields to executions table."""
    db_path = temp_workspace / ".lonelycat" / "executor.db"

    # Initialize database (runs migrations)
    init_executor_db(db_path)

    # Check schema
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(executions)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()

    # Verify new fields exist
    assert "correlation_id" in columns
    assert "parent_execution_id" in columns
    assert "trigger_kind" in columns
    assert "run_id" in columns

    print(f"[OK] Graph fields added: {columns & {'correlation_id', 'parent_execution_id', 'trigger_kind', 'run_id'}}")


# ========== Test 2: Record Execution with Graph Fields ==========

def test_record_execution_with_graph_fields(temp_workspace):
    """Test recording execution with correlation and parent."""
    store = ExecutionStore(temp_workspace)

    # Record root execution
    store.record_execution_start(
        execution_id="exec_root",
        plan_id="plan_1",
        changeset_id="changeset_1",
        decision_id="decision_1",
        checksum="checksum_1",
        verdict="allow",
        risk_level="low",
        affected_paths=["file1.py"],
        artifact_path=str(temp_workspace / "exec_root"),
        correlation_id="corr_123",
        parent_execution_id=None,
        trigger_kind="manual",
        run_id="run_1"
    )

    # Retrieve and verify
    execution = store.get_execution("exec_root")

    assert execution is not None
    assert execution.correlation_id == "corr_123"
    assert execution.parent_execution_id is None
    assert execution.trigger_kind == "manual"
    assert execution.run_id == "run_1"

    print(f"[OK] Recorded execution with graph fields: correlation_id={execution.correlation_id}")


def test_record_child_execution(temp_workspace):
    """Test recording child execution with parent link."""
    store = ExecutionStore(temp_workspace)

    # Record parent execution
    store.record_execution_start(
        execution_id="exec_parent",
        plan_id="plan_1",
        changeset_id="changeset_1",
        decision_id="decision_1",
        checksum="checksum_1",
        verdict="allow",
        risk_level="low",
        affected_paths=["file1.py"],
        artifact_path=str(temp_workspace / "exec_parent"),
        correlation_id="corr_chain",
        parent_execution_id=None,
        trigger_kind="manual"
    )

    # Record child execution (retry)
    store.record_execution_start(
        execution_id="exec_child",
        plan_id="plan_2",
        changeset_id="changeset_2",
        decision_id="decision_2",
        checksum="checksum_2",
        verdict="allow",
        risk_level="low",
        affected_paths=["file1.py"],
        artifact_path=str(temp_workspace / "exec_child"),
        correlation_id="corr_chain",  # Same correlation
        parent_execution_id="exec_parent",  # Link to parent
        trigger_kind="retry"
    )

    # Verify parent link
    child = store.get_execution("exec_child")
    assert child.parent_execution_id == "exec_parent"
    assert child.correlation_id == "corr_chain"
    assert child.trigger_kind == "retry"

    print(f"[OK] Child execution linked: parent={child.parent_execution_id}, trigger={child.trigger_kind}")


# ========== Test 3: Lineage Queries ==========

def test_get_execution_lineage(temp_workspace):
    """Test getting execution lineage (ancestors + descendants)."""
    store = ExecutionStore(temp_workspace)

    # Create execution chain: root -> child1 -> grandchild
    store.record_execution_start(
        execution_id="exec_root",
        plan_id="plan_1",
        changeset_id="cs_1",
        decision_id="dec_1",
        checksum="sum_1",
        verdict="allow",
        risk_level="low",
        affected_paths=[],
        artifact_path=str(temp_workspace / "exec_root"),
        correlation_id="corr_lineage",
        parent_execution_id=None,
        trigger_kind="manual"
    )

    store.record_execution_start(
        execution_id="exec_child1",
        plan_id="plan_2",
        changeset_id="cs_2",
        decision_id="dec_2",
        checksum="sum_2",
        verdict="allow",
        risk_level="low",
        affected_paths=[],
        artifact_path=str(temp_workspace / "exec_child1"),
        correlation_id="corr_lineage",
        parent_execution_id="exec_root",
        trigger_kind="retry"
    )

    store.record_execution_start(
        execution_id="exec_grandchild",
        plan_id="plan_3",
        changeset_id="cs_3",
        decision_id="dec_3",
        checksum="sum_3",
        verdict="allow",
        risk_level="low",
        affected_paths=[],
        artifact_path=str(temp_workspace / "exec_grandchild"),
        correlation_id="corr_lineage",
        parent_execution_id="exec_child1",
        trigger_kind="repair"
    )

    # Get lineage for middle node
    lineage = store.get_execution_lineage("exec_child1")

    # Should have 1 ancestor (root)
    assert len(lineage["ancestors"]) == 1
    assert lineage["ancestors"][0].execution_id == "exec_root"

    # Should have 1 descendant (grandchild)
    assert len(lineage["descendants"]) == 1
    assert lineage["descendants"][0].execution_id == "exec_grandchild"

    # Should have no siblings
    assert len(lineage["siblings"]) == 0

    print(f"[OK] Lineage: ancestors={len(lineage['ancestors'])}, descendants={len(lineage['descendants'])}")


def test_get_execution_lineage_with_siblings(temp_workspace):
    """Test lineage with siblings (same parent)."""
    store = ExecutionStore(temp_workspace)

    # Create tree: root -> (child1, child2, child3)
    store.record_execution_start(
        execution_id="exec_root",
        plan_id="p1",
        changeset_id="cs1",
        decision_id="d1",
        checksum="s1",
        verdict="allow",
        risk_level="low",
        affected_paths=[],
        artifact_path=str(temp_workspace / "exec_root"),
        correlation_id="corr_siblings",
        parent_execution_id=None
    )

    for i in range(1, 4):
        store.record_execution_start(
            execution_id=f"exec_child{i}",
            plan_id=f"p{i+1}",
            changeset_id=f"cs{i+1}",
            decision_id=f"d{i+1}",
            checksum=f"s{i+1}",
            verdict="allow",
            risk_level="low",
            affected_paths=[],
            artifact_path=str(temp_workspace / f"exec_child{i}"),
            correlation_id="corr_siblings",
            parent_execution_id="exec_root"
        )

    # Get lineage for child2
    lineage = store.get_execution_lineage("exec_child2")

    # Should have 1 ancestor (root)
    assert len(lineage["ancestors"]) == 1

    # Should have 2 siblings (child1, child3)
    assert len(lineage["siblings"]) == 2
    sibling_ids = {s.execution_id for s in lineage["siblings"]}
    assert sibling_ids == {"exec_child1", "exec_child3"}

    print(f"[OK] Siblings: {sibling_ids}")


# ========== Test 4: Correlation Queries ==========

def test_list_executions_by_correlation(temp_workspace):
    """Test listing all executions in a correlation chain."""
    store = ExecutionStore(temp_workspace)

    # Create executions with same correlation
    for i in range(3):
        store.record_execution_start(
            execution_id=f"exec_{i}",
            plan_id=f"plan_{i}",
            changeset_id=f"cs_{i}",
            decision_id=f"dec_{i}",
            checksum=f"sum_{i}",
            verdict="allow",
            risk_level="low",
            affected_paths=[],
            artifact_path=str(temp_workspace / f"exec_{i}"),
            correlation_id="corr_same",
            parent_execution_id=f"exec_{i-1}" if i > 0 else None
        )

    # Query by correlation
    executions = store.list_executions_by_correlation("corr_same")

    assert len(executions) == 3
    assert executions[0].execution_id == "exec_0"
    assert executions[1].execution_id == "exec_1"
    assert executions[2].execution_id == "exec_2"

    print(f"[OK] Correlation chain: {[e.execution_id for e in executions]}")


def test_get_root_execution(temp_workspace):
    """Test getting root execution of a correlation chain."""
    store = ExecutionStore(temp_workspace)

    # Create chain with root
    store.record_execution_start(
        execution_id="exec_root",
        plan_id="p1",
        changeset_id="cs1",
        decision_id="d1",
        checksum="s1",
        verdict="allow",
        risk_level="low",
        affected_paths=[],
        artifact_path=str(temp_workspace / "exec_root"),
        correlation_id="corr_root",
        parent_execution_id=None
    )

    store.record_execution_start(
        execution_id="exec_child",
        plan_id="p2",
        changeset_id="cs2",
        decision_id="d2",
        checksum="s2",
        verdict="allow",
        risk_level="low",
        affected_paths=[],
        artifact_path=str(temp_workspace / "exec_child"),
        correlation_id="corr_root",
        parent_execution_id="exec_root"
    )

    # Get root
    root = store.get_root_execution("corr_root")

    assert root is not None
    assert root.execution_id == "exec_root"
    assert root.parent_execution_id is None

    print(f"[OK] Root execution: {root.execution_id}")


# ========== Test 5: Default Correlation ID ==========

def test_default_correlation_id(temp_workspace):
    """Test that correlation_id defaults to execution_id for root executions."""
    store = ExecutionStore(temp_workspace)

    # Record without explicit correlation_id
    store.record_execution_start(
        execution_id="exec_default",
        plan_id="p1",
        changeset_id="cs1",
        decision_id="d1",
        checksum="s1",
        verdict="allow",
        risk_level="low",
        affected_paths=[],
        artifact_path=str(temp_workspace / "exec_default")
        # Note: No correlation_id provided
    )

    # Should default to execution_id
    execution = store.get_execution("exec_default")
    assert execution.correlation_id == "exec_default"

    print(f"[OK] Default correlation_id: {execution.correlation_id}")


# ========== Run All Tests ==========

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
