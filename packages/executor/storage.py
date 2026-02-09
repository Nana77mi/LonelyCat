"""
Execution Store - Phase 2.2-B

Provides database operations for execution history.

Features:
- Record execution start/end
- Track execution steps with timing
- Query recent executions
- Filter by status/risk/verdict
- Update execution status
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from .schema import init_executor_db, get_db_connection


@dataclass
class ExecutionRecord:
    """Execution record from database."""
    execution_id: str
    plan_id: str
    changeset_id: str
    decision_id: str
    checksum: str
    verdict: str
    status: str
    risk_level: Optional[str]
    affected_paths: List[str]
    started_at: str
    ended_at: Optional[str]
    duration_seconds: Optional[float]
    files_changed: int
    verification_passed: bool
    health_checks_passed: bool
    rolled_back: bool
    artifact_path: Optional[str]
    error_message: Optional[str]
    error_step: Optional[str]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ExecutionRecord":
        """Create ExecutionRecord from database row."""
        return cls(
            execution_id=row["execution_id"],
            plan_id=row["plan_id"],
            changeset_id=row["changeset_id"],
            decision_id=row["decision_id"],
            checksum=row["checksum"],
            verdict=row["verdict"],
            status=row["status"],
            risk_level=row["risk_level"],
            affected_paths=json.loads(row["affected_paths"]) if row["affected_paths"] else [],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            duration_seconds=row["duration_seconds"],
            files_changed=row["files_changed"],
            verification_passed=bool(row["verification_passed"]),
            health_checks_passed=bool(row["health_checks_passed"]),
            rolled_back=bool(row["rolled_back"]),
            artifact_path=row["artifact_path"],
            error_message=row["error_message"],
            error_step=row["error_step"]
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "changeset_id": self.changeset_id,
            "decision_id": self.decision_id,
            "checksum": self.checksum,
            "verdict": self.verdict,
            "status": self.status,
            "risk_level": self.risk_level,
            "affected_paths": self.affected_paths,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "files_changed": self.files_changed,
            "verification_passed": self.verification_passed,
            "health_checks_passed": self.health_checks_passed,
            "rolled_back": self.rolled_back,
            "artifact_path": self.artifact_path,
            "error_message": self.error_message,
            "error_step": self.error_step
        }


@dataclass
class StepRecord:
    """Execution step record from database."""
    id: int
    execution_id: str
    step_num: int
    step_name: str
    status: str
    started_at: str
    ended_at: Optional[str]
    duration_seconds: Optional[float]
    error_code: Optional[str]
    error_message: Optional[str]
    log_ref: Optional[str]
    metadata: Optional[Dict[str, Any]]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "StepRecord":
        """Create StepRecord from database row."""
        return cls(
            id=row["id"],
            execution_id=row["execution_id"],
            step_num=row["step_num"],
            step_name=row["step_name"],
            status=row["status"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            duration_seconds=row["duration_seconds"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            log_ref=row["log_ref"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else None
        )


class ExecutionStore:
    """
    Manages execution history in SQLite.

    Responsibilities:
    - Record execution start (insert)
    - Update execution status/results
    - Record execution steps with timing
    - Query executions (recent, filtered)
    - Get execution details
    """

    def __init__(self, workspace_root: Path):
        """
        Initialize execution store.

        Args:
            workspace_root: Workspace root directory
        """
        self.workspace_root = Path(workspace_root).resolve()
        self.db_path = self.workspace_root / ".lonelycat" / "executor.db"

        # Ensure database is initialized
        init_executor_db(self.db_path)

    def record_execution_start(
        self,
        execution_id: str,
        plan_id: str,
        changeset_id: str,
        decision_id: str,
        checksum: str,
        verdict: str,
        risk_level: str,
        affected_paths: List[str],
        artifact_path: str
    ):
        """
        Record execution start.

        Args:
            execution_id: Unique execution ID
            plan_id: Plan ID
            changeset_id: ChangeSet ID
            decision_id: Decision ID
            checksum: ChangeSet checksum
            verdict: Governance verdict (allow, need_approval, deny)
            risk_level: Risk level (low, medium, high, critical)
            affected_paths: List of affected file paths
            artifact_path: Path to artifact directory
        """
        conn = get_db_connection(self.db_path)
        try:
            conn.execute("""
                INSERT INTO executions (
                    execution_id, plan_id, changeset_id, decision_id,
                    checksum, verdict, status, risk_level, affected_paths,
                    started_at, artifact_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                execution_id,
                plan_id,
                changeset_id,
                decision_id,
                checksum,
                verdict,
                "pending",
                risk_level,
                json.dumps(affected_paths),
                datetime.utcnow().isoformat(),
                artifact_path
            ))
            conn.commit()
        finally:
            conn.close()

    def update_execution_status(
        self,
        execution_id: str,
        status: str,
        error_message: Optional[str] = None,
        error_step: Optional[str] = None
    ):
        """
        Update execution status.

        Args:
            execution_id: Execution ID
            status: New status
            error_message: Error message (if failed)
            error_step: Step where error occurred
        """
        conn = get_db_connection(self.db_path)
        try:
            conn.execute("""
                UPDATE executions
                SET status = ?, error_message = ?, error_step = ?
                WHERE execution_id = ?
            """, (status, error_message, error_step, execution_id))
            conn.commit()
        finally:
            conn.close()

    def record_execution_end(
        self,
        execution_id: str,
        status: str,
        duration_seconds: float,
        files_changed: int,
        verification_passed: bool,
        health_checks_passed: bool,
        rolled_back: bool,
        error_message: Optional[str] = None,
        error_step: Optional[str] = None
    ):
        """
        Record execution end with results.

        Args:
            execution_id: Execution ID
            status: Final status (completed, failed, rolled_back)
            duration_seconds: Execution duration
            files_changed: Number of files changed
            verification_passed: Verification result
            health_checks_passed: Health check result
            rolled_back: Whether rollback occurred
            error_message: Error message (if failed)
            error_step: Step where error occurred
        """
        conn = get_db_connection(self.db_path)
        try:
            conn.execute("""
                UPDATE executions
                SET status = ?,
                    ended_at = ?,
                    duration_seconds = ?,
                    files_changed = ?,
                    verification_passed = ?,
                    health_checks_passed = ?,
                    rolled_back = ?,
                    error_message = ?,
                    error_step = ?
                WHERE execution_id = ?
            """, (
                status,
                datetime.utcnow().isoformat(),
                duration_seconds,
                files_changed,
                1 if verification_passed else 0,
                1 if health_checks_passed else 0,
                1 if rolled_back else 0,
                error_message,
                error_step,
                execution_id
            ))
            conn.commit()
        finally:
            conn.close()

    def record_step_start(
        self,
        execution_id: str,
        step_num: int,
        step_name: str,
        log_ref: Optional[str] = None
    ) -> int:
        """
        Record step start.

        Args:
            execution_id: Execution ID
            step_num: Step number
            step_name: Step name (validate, backup, apply, verify, health, rollback)
            log_ref: Reference to log file (e.g., steps/01_validate.log)

        Returns:
            Step record ID
        """
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.execute("""
                INSERT INTO execution_steps (
                    execution_id, step_num, step_name, status, started_at, log_ref
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                execution_id,
                step_num,
                step_name,
                "running",
                datetime.utcnow().isoformat(),
                log_ref
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def record_step_end(
        self,
        step_id: int,
        status: str,
        duration_seconds: float,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        """
        Record step end.

        Args:
            step_id: Step record ID
            status: Final status (completed, failed)
            duration_seconds: Step duration
            error_code: Error code (if failed)
            error_message: Error message (if failed)
        """
        conn = get_db_connection(self.db_path)
        try:
            conn.execute("""
                UPDATE execution_steps
                SET status = ?,
                    ended_at = ?,
                    duration_seconds = ?,
                    error_code = ?,
                    error_message = ?
                WHERE id = ?
            """, (
                status,
                datetime.utcnow().isoformat(),
                duration_seconds,
                error_code,
                error_message,
                step_id
            ))
            conn.commit()
        finally:
            conn.close()

    def get_execution(self, execution_id: str) -> Optional[ExecutionRecord]:
        """
        Get execution record by ID.

        Args:
            execution_id: Execution ID

        Returns:
            ExecutionRecord or None if not found
        """
        conn = get_db_connection(self.db_path)
        try:
            row = conn.execute("""
                SELECT * FROM executions WHERE execution_id = ?
            """, (execution_id,)).fetchone()

            if row:
                return ExecutionRecord.from_row(row)
            return None
        finally:
            conn.close()

    def list_executions(
        self,
        limit: int = 20,
        status: Optional[str] = None,
        verdict: Optional[str] = None,
        risk_level: Optional[str] = None
    ) -> List[ExecutionRecord]:
        """
        List recent executions with optional filters.

        Args:
            limit: Maximum number of records to return
            status: Filter by status (optional)
            verdict: Filter by verdict (optional)
            risk_level: Filter by risk level (optional)

        Returns:
            List of ExecutionRecord
        """
        conn = get_db_connection(self.db_path)
        try:
            # Build query with filters
            query = "SELECT * FROM executions WHERE 1=1"
            params = []

            if status:
                query += " AND status = ?"
                params.append(status)
            if verdict:
                query += " AND verdict = ?"
                params.append(verdict)
            if risk_level:
                query += " AND risk_level = ?"
                params.append(risk_level)

            query += " ORDER BY started_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [ExecutionRecord.from_row(row) for row in rows]
        finally:
            conn.close()

    def get_execution_steps(self, execution_id: str) -> List[StepRecord]:
        """
        Get all steps for an execution.

        Args:
            execution_id: Execution ID

        Returns:
            List of StepRecord ordered by step_num
        """
        conn = get_db_connection(self.db_path)
        try:
            rows = conn.execute("""
                SELECT * FROM execution_steps
                WHERE execution_id = ?
                ORDER BY step_num ASC
            """, (execution_id,)).fetchall()

            return [StepRecord.from_row(row) for row in rows]
        finally:
            conn.close()

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get execution statistics.

        Returns:
            Dict with statistics (total, by status, avg duration, etc.)
        """
        conn = get_db_connection(self.db_path)
        try:
            # Total executions
            total = conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]

            # By status
            status_counts = {}
            rows = conn.execute("""
                SELECT status, COUNT(*) as count FROM executions GROUP BY status
            """).fetchall()
            for row in rows:
                status_counts[row["status"]] = row["count"]

            # Average duration
            avg_duration = conn.execute("""
                SELECT AVG(duration_seconds) FROM executions WHERE duration_seconds IS NOT NULL
            """).fetchone()[0]

            # Success rate
            completed = status_counts.get("completed", 0)
            failed = status_counts.get("failed", 0) + status_counts.get("rolled_back", 0)
            success_rate = (completed / (completed + failed) * 100) if (completed + failed) > 0 else 0

            return {
                "total_executions": total,
                "by_status": status_counts,
                "avg_duration_seconds": avg_duration,
                "success_rate_percent": success_rate
            }
        finally:
            conn.close()
