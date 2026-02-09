"""
Tests for Reflection Analysis Script - Phase 2.3-C

Validates:
- C1: 失败归因摘要功能
- C2: WriteGate 反馈信号（false allow/deny）
- Database query functions
- Report generation
"""

import pytest
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import sys

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from reflection_analysis import (
    FailedExecution,
    get_failed_executions,
    get_allow_executions,
    get_deny_executions,
    analyze_failure_attribution,
    analyze_false_allow,
    analyze_potential_false_deny,
    generate_reflection_report,
)

# Add packages to path for executor schema
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "packages"))
from executor.storage import init_executor_db


@pytest.fixture
def test_db():
    """Create test database with sample data"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "executor.db"

        # Initialize database
        init_executor_db(db_path)

        # Insert sample executions
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Sample data: 3 failed, 2 allow+completed, 1 deny
        test_data = [
            # Failed executions
            (
                "exec_failed_1",
                "plan_1",
                "changeset_1",
                "decision_1",
                "checksum_1",
                "failed",
                "allow",
                "low",
                '["file1.py"]',
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                1.5,
                2,
                False,
                False,
                False,
                "validate",
                "[VALIDATION_ERROR] File not found",
                str(Path(tmpdir) / "exec_failed_1"),
            ),
            (
                "exec_failed_2",
                "plan_2",
                "changeset_2",
                "decision_2",
                "checksum_2",
                "failed",
                "allow",
                "medium",
                '["file2.py"]',
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                2.3,
                3,
                False,
                False,
                False,
                "apply",
                "[APPLY_ERROR] Permission denied",
                str(Path(tmpdir) / "exec_failed_2"),
            ),
            (
                "exec_rolled_back",
                "plan_3",
                "changeset_3",
                "decision_3",
                "checksum_3",
                "rolled_back",
                "allow",
                "high",
                '["file3.py"]',
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                3.0,
                5,
                False,
                False,
                True,
                "verify",
                "Test failed",
                str(Path(tmpdir) / "exec_rolled_back"),
            ),
            # Successful allow executions
            (
                "exec_success_1",
                "plan_4",
                "changeset_4",
                "decision_4",
                "checksum_4",
                "completed",
                "allow",
                "low",
                '["file4.py"]',
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                1.0,
                2,
                True,
                True,
                False,
                None,
                None,
                str(Path(tmpdir) / "exec_success_1"),
            ),
            (
                "exec_success_2",
                "plan_5",
                "changeset_5",
                "decision_5",
                "checksum_5",
                "completed",
                "allow",
                "low",
                '["file5.py"]',
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                1.2,
                1,
                True,
                True,
                False,
                None,
                None,
                str(Path(tmpdir) / "exec_success_2"),
            ),
            # Deny execution
            (
                "exec_deny_1",
                "plan_6",
                "changeset_6",
                "decision_6",
                "checksum_6",
                "pending",
                "deny",
                "critical",
                '[]',
                datetime.now(timezone.utc).isoformat(),
                None,
                None,
                0,
                False,
                False,
                False,
                None,
                None,
                None,
            ),
        ]

        for data in test_data:
            cursor.execute(
                """
                INSERT INTO executions (
                    execution_id, plan_id, changeset_id, decision_id, checksum,
                    status, verdict, risk_level, affected_paths,
                    started_at, ended_at, duration_seconds, files_changed,
                    verification_passed, health_checks_passed, rolled_back,
                    error_step, error_message, artifact_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                data,
            )

        conn.commit()
        conn.close()

        yield db_path


# ========== Test 1: Get Failed Executions ==========

def test_get_failed_executions(test_db):
    """Test fetching failed executions from database"""
    executions = get_failed_executions(test_db, limit=10)

    assert len(executions) == 3  # 2 failed + 1 rolled_back

    # Check data structure
    for exec in executions:
        assert isinstance(exec, FailedExecution)
        assert exec.execution_id.startswith("exec_")
        assert exec.status in ("failed", "rolled_back")
        assert exec.error_step is not None
        assert exec.error_message is not None

    print(f"[OK] Fetched {len(executions)} failed executions")


# ========== Test 2: Get Allow Executions ==========

def test_get_allow_executions(test_db):
    """Test fetching allow executions"""
    executions = get_allow_executions(test_db, limit=10)

    assert len(executions) == 5  # 2 failed + 1 rolled_back + 2 success

    for exec in executions:
        assert exec["verdict"] == "allow"

    print(f"[OK] Fetched {len(executions)} allow executions")


# ========== Test 3: Get Deny Executions ==========

def test_get_deny_executions(test_db):
    """Test fetching deny executions"""
    executions = get_deny_executions(test_db, limit=10)

    assert len(executions) == 1
    assert executions[0]["verdict"] == "deny"

    print("[OK] Fetched deny executions")


# ========== Test 4: Failure Attribution Analysis ==========

def test_analyze_failure_attribution(test_db):
    """Test C1: 失败归因摘要"""
    executions = get_failed_executions(test_db, limit=10)
    analysis = analyze_failure_attribution(executions)

    # Check structure
    assert "total_failed" in analysis
    assert "top_error_steps" in analysis
    assert "top_error_codes" in analysis
    assert "avg_failure_duration" in analysis
    assert "failure_by_risk_level" in analysis
    assert "failures" in analysis

    # Check values
    assert analysis["total_failed"] == 3
    assert len(analysis["top_error_steps"]) > 0
    assert len(analysis["top_error_codes"]) > 0
    assert analysis["avg_failure_duration"] > 0

    # Check top error steps
    error_steps = [step for step, count in analysis["top_error_steps"]]
    assert "validate" in error_steps or "apply" in error_steps or "verify" in error_steps

    # Check failure by risk level
    assert "low" in analysis["failure_by_risk_level"] or \
           "medium" in analysis["failure_by_risk_level"] or \
           "high" in analysis["failure_by_risk_level"]

    print(f"[OK] Failure attribution analysis:")
    print(f"  Total failed: {analysis['total_failed']}")
    print(f"  Top error steps: {analysis['top_error_steps']}")
    print(f"  Avg duration: {analysis['avg_failure_duration']}s")


# ========== Test 5: False Allow Analysis ==========

def test_analyze_false_allow(test_db):
    """Test C2: False Allow detection"""
    executions = get_allow_executions(test_db, limit=10)
    analysis = analyze_false_allow(executions)

    # Check structure
    assert "total_allow" in analysis
    assert "total_false_allow" in analysis
    assert "false_allow_rate" in analysis
    assert "cases" in analysis

    # Check values
    assert analysis["total_allow"] == 5
    assert analysis["total_false_allow"] == 3  # 2 failed + 1 rolled_back
    assert analysis["false_allow_rate"] == 60.0  # 3/5 * 100

    # Check cases
    assert len(analysis["cases"]) == 3
    for case in analysis["cases"]:
        assert "execution_id" in case
        assert "error_step" in case
        assert "error_message" in case

    print(f"[OK] False allow analysis:")
    print(f"  Total allow: {analysis['total_allow']}")
    print(f"  False allow: {analysis['total_false_allow']}")
    print(f"  Rate: {analysis['false_allow_rate']}%")


# ========== Test 6: Potential False Deny Analysis ==========

def test_analyze_potential_false_deny(test_db):
    """Test C2: Potential False Deny detection"""
    executions = get_deny_executions(test_db, limit=10)
    analysis = analyze_potential_false_deny(executions)

    # Check structure
    assert "total_deny" in analysis
    assert "potential_false_deny_count" in analysis
    assert "note" in analysis
    assert "cases" in analysis

    # Check values
    assert analysis["total_deny"] == 1
    assert "manual review" in analysis["note"]

    print(f"[OK] Potential false deny analysis:")
    print(f"  Total deny: {analysis['total_deny']}")
    print(f"  Note: {analysis['note']}")


# ========== Test 7: Full Report Generation ==========

def test_generate_reflection_report(test_db):
    """Test full report generation"""
    workspace = test_db.parent

    # Create .lonelycat directory and move database there
    lonelycat_dir = workspace / ".lonelycat"
    lonelycat_dir.mkdir(exist_ok=True)

    # Copy database to .lonelycat/executor.db
    import shutil
    target_db = lonelycat_dir / "executor.db"
    shutil.copy2(test_db, target_db)

    report = generate_reflection_report(workspace, failed_limit=10)

    # Check top-level structure
    assert "generated_at" in report
    assert "workspace_root" in report
    assert "summary" in report
    assert "failure_attribution" in report
    assert "writegate_feedback" in report

    # Check summary
    summary = report["summary"]
    assert summary["total_failed"] == 3
    assert summary["total_allow"] == 5
    assert summary["total_deny"] == 1
    assert summary["false_allow_rate"] == 60.0

    # Check failure attribution section
    failure = report["failure_attribution"]
    assert failure["total_failed"] == 3
    assert len(failure["top_error_steps"]) > 0
    assert failure["avg_failure_duration"] > 0

    # Check writegate feedback section
    writegate = report["writegate_feedback"]
    assert "false_allow" in writegate
    assert "potential_false_deny" in writegate

    false_allow = writegate["false_allow"]
    assert false_allow["total_false_allow"] == 3
    assert false_allow["false_allow_rate"] == 60.0

    print(f"[OK] Full report generated successfully")
    print(f"  Generated at: {report['generated_at']}")
    print(f"  False allow rate: {summary['false_allow_rate']}%")


# ========== Test 8: Empty Database ==========

def test_empty_database():
    """Test handling of empty database"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "empty.db"
        init_executor_db(db_path)

        executions = get_failed_executions(db_path, limit=10)
        assert len(executions) == 0

        analysis = analyze_failure_attribution(executions)
        assert analysis["total_failed"] == 0
        assert len(analysis["top_error_steps"]) == 0
        assert analysis["avg_failure_duration"] == 0.0

        print("[OK] Empty database handled correctly")


# ========== Run All Tests ==========

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
