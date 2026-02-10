"""
Execution Store - Phase 2.4-D (Updated)

Provides database operations for execution history.

Features:
- Record execution start/end with graph metadata
- Track execution steps with timing
- Query recent executions
- Filter by status/risk/verdict
- Query execution lineage (graph traversal)
- Find similar executions (Phase 2.4-D)
- Update execution status
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from .schema import init_executor_db, get_db_connection
from .similarity import SimilarityEngine, SimilarityScore


@dataclass
class ExecutionRecord:
    """Execution record from database (Phase 2.4-A with graph fields)."""
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

    # Phase 2.4-A: Execution Graph fields
    correlation_id: Optional[str] = None
    parent_execution_id: Optional[str] = None
    trigger_kind: Optional[str] = None
    run_id: Optional[str] = None
    # Phase 2.5-D: Repair in graph
    is_repair: bool = False
    repair_for_execution_id: Optional[str] = None

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
            error_step=row["error_step"],
            # Graph fields (may be None for old records)
            correlation_id=row["correlation_id"] if "correlation_id" in row.keys() else None,
            parent_execution_id=row["parent_execution_id"] if "parent_execution_id" in row.keys() else None,
            trigger_kind=row["trigger_kind"] if "trigger_kind" in row.keys() else None,
            run_id=row["run_id"] if "run_id" in row.keys() else None,
            is_repair=bool(row["is_repair"]) if "is_repair" in row.keys() and row["is_repair"] else False,
            repair_for_execution_id=row["repair_for_execution_id"] if "repair_for_execution_id" in row.keys() else None,
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
            "error_step": self.error_step,
            # Graph fields
            "correlation_id": self.correlation_id,
            "parent_execution_id": self.parent_execution_id,
            "trigger_kind": self.trigger_kind,
            "run_id": self.run_id,
            "is_repair": self.is_repair,
            "repair_for_execution_id": self.repair_for_execution_id,
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
        artifact_path: str,
        # Phase 2.4-A: Graph fields
        correlation_id: Optional[str] = None,
        parent_execution_id: Optional[str] = None,
        trigger_kind: str = "manual",
        run_id: Optional[str] = None,
        is_repair: bool = False,
        repair_for_execution_id: Optional[str] = None,
    ):
        """
        Record execution start (Phase 2.4-A with graph metadata, 2.5-D repair fields).

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
            correlation_id: Correlation ID for task chain (None = use execution_id)
            parent_execution_id: Parent execution ID (for retry/repair/child)
            trigger_kind: How execution was triggered (manual/agent/retry/repair/child/scheduled)
            run_id: Optional run system ID
            is_repair: True if this execution is a repair run (Phase 2.5-D)
            repair_for_execution_id: Failed execution ID this repair is for (Phase 2.5-D)
        """
        # Default correlation_id to execution_id if not provided (root execution)
        if correlation_id is None:
            correlation_id = execution_id

        conn = get_db_connection(self.db_path)
        try:
            columns = [
                "execution_id", "plan_id", "changeset_id", "decision_id",
                "checksum", "verdict", "status", "risk_level", "affected_paths",
                "started_at", "artifact_path",
                "correlation_id", "parent_execution_id", "trigger_kind", "run_id"
            ]
            placeholders = ["?"] * len(columns)
            values = [
                execution_id, plan_id, changeset_id, decision_id,
                checksum, verdict, "pending", risk_level, json.dumps(affected_paths),
                datetime.utcnow().isoformat(), artifact_path,
                correlation_id, parent_execution_id, trigger_kind, run_id
            ]
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(executions)")
            cols = [row[1] for row in cursor.fetchall()]
            if "is_repair" in cols and "repair_for_execution_id" in cols:
                columns.extend(["is_repair", "repair_for_execution_id"])
                placeholders.extend(["?", "?"])
                values.extend([1 if is_repair else 0, repair_for_execution_id])
            conn.execute(
                f"INSERT INTO executions ({', '.join(columns)}) VALUES ({', '.join(placeholders)})",
                tuple(values)
            )
            # Phase 2.5-B: dual-write to execution_paths
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='execution_paths'")
            if cursor.fetchone() and affected_paths:
                for p in affected_paths:
                    if p and isinstance(p, str) and p.strip():
                        cursor.execute(
                            "INSERT OR IGNORE INTO execution_paths (execution_id, path) VALUES (?, ?)",
                            (execution_id, p.strip())
                        )
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

    # ==================== Phase 2.4-A: Execution Graph Queries ====================

    def get_execution_lineage(
        self,
        execution_id: str,
        depth: int = 20
    ) -> Dict[str, Any]:
        """
        Get execution lineage (ancestors + descendants).

        Args:
            execution_id: Execution ID to get lineage for
            depth: Maximum depth to traverse (prevents infinite loops)

        Returns:
            Dict with:
                - execution: The target execution
                - ancestors: List of parent executions (root -> current)
                - descendants: List of child executions (tree)
                - siblings: List of executions with same parent
        """
        conn = get_db_connection(self.db_path)
        try:
            # Get target execution
            execution = self.get_execution(execution_id)
            if not execution:
                return {
                    "execution": None,
                    "ancestors": [],
                    "descendants": [],
                    "siblings": []
                }

            # Get ancestors (walk up parent chain)
            ancestors = []
            current_id = execution.parent_execution_id
            visited = set()

            while current_id and len(ancestors) < depth:
                if current_id in visited:
                    break  # Circular reference protection
                visited.add(current_id)

                parent = self.get_execution(current_id)
                if not parent:
                    break

                ancestors.append(parent)
                current_id = parent.parent_execution_id

            # Reverse to get root -> current order
            ancestors.reverse()

            # Get descendants (BFS traversal)
            descendants = []
            queue = [execution_id]
            visited = set()

            while queue and len(descendants) < depth * 10:  # Limit total descendants
                current_id = queue.pop(0)

                if current_id in visited:
                    continue
                visited.add(current_id)

                # Get children
                children_rows = conn.execute("""
                    SELECT * FROM executions
                    WHERE parent_execution_id = ?
                    ORDER BY started_at ASC
                """, (current_id,)).fetchall()

                for row in children_rows:
                    child = ExecutionRecord.from_row(row)
                    descendants.append(child)
                    queue.append(child.execution_id)

            # Get siblings (same parent)
            siblings = []
            if execution.parent_execution_id:
                sibling_rows = conn.execute("""
                    SELECT * FROM executions
                    WHERE parent_execution_id = ? AND execution_id != ?
                    ORDER BY started_at ASC
                """, (execution.parent_execution_id, execution_id)).fetchall()

                siblings = [ExecutionRecord.from_row(row) for row in sibling_rows]

            return {
                "execution": execution,
                "ancestors": ancestors,
                "descendants": descendants,
                "siblings": siblings
            }

        finally:
            conn.close()

    def list_executions_by_correlation(
        self,
        correlation_id: str,
        limit: int = 100
    ) -> List[ExecutionRecord]:
        """
        List all executions in a correlation chain.

        Args:
            correlation_id: Correlation ID to filter by
            limit: Maximum number of executions to return

        Returns:
            List of execution records (chronological order)
        """
        conn = get_db_connection(self.db_path)
        try:
            rows = conn.execute("""
                SELECT * FROM executions
                WHERE correlation_id = ?
                ORDER BY started_at ASC
                LIMIT ?
            """, (correlation_id, limit)).fetchall()

            return [ExecutionRecord.from_row(row) for row in rows]

        finally:
            conn.close()

    def get_root_execution(self, correlation_id: str) -> Optional[ExecutionRecord]:
        """
        Get root execution for a correlation chain.

        Root = execution with no parent_execution_id in this correlation.

        Args:
            correlation_id: Correlation ID

        Returns:
            Root execution record or None
        """
        conn = get_db_connection(self.db_path)
        try:
            row = conn.execute("""
                SELECT * FROM executions
                WHERE correlation_id = ? AND parent_execution_id IS NULL
                ORDER BY started_at ASC
                LIMIT 1
            """, (correlation_id,)).fetchone()

            return ExecutionRecord.from_row(row) if row else None

        finally:
            conn.close()

    # ==================== Phase 2.4-D: Similarity Queries (2.5-B: execution_paths) ====================

    def _execution_paths_table_exists(self, cursor: sqlite3.Cursor) -> bool:
        """Return True if execution_paths table exists (Phase 2.5-B)."""
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='execution_paths'")
        return cursor.fetchone() is not None

    def _get_paths_for_execution(
        self, conn: sqlite3.Connection, execution_id: str, fallback_paths: List[str]
    ) -> List[str]:
        """Get paths for an execution: prefer execution_paths table, else fallback (Phase 2.5-B)."""
        cursor = conn.cursor()
        if not self._execution_paths_table_exists(cursor):
            return fallback_paths
        cursor.execute("SELECT path FROM execution_paths WHERE execution_id = ? ORDER BY path", (execution_id,))
        rows = cursor.fetchall()
        if rows:
            return [r[0] for r in rows]
        return fallback_paths

    def find_similar_executions(
        self,
        execution_id: str,
        limit: int = 5,
        min_similarity: float = 0.3,
        exclude_same_correlation: bool = True
    ) -> List[Tuple[ExecutionRecord, SimilarityScore]]:
        """
        Find executions similar to the given execution (Phase 2.4-D).

        Similarity based on:
        - Error message (text similarity)
        - Affected paths (Jaccard similarity)
        - Status and verdict matching

        Use cases:
        - When execution fails, find similar historical failures
        - Find how similar issues were resolved
        - Debug by finding "what worked last time"

        Args:
            execution_id: Target execution to find similar to
            limit: Maximum number of similar executions to return
            min_similarity: Minimum similarity threshold (0.0 to 1.0)
            exclude_same_correlation: If True, exclude executions from same correlation chain

        Returns:
            List of (ExecutionRecord, SimilarityScore) tuples, sorted by similarity (highest first)
        """
        # Get target execution
        target = self.get_execution(execution_id)
        if not target:
            return []

        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.cursor()
            target_paths = self._get_paths_for_execution(conn, execution_id, target.affected_paths)

            # Candidate set: prefer execution_paths (path overlap), else fallback to recent 1000
            rows = []
            if target_paths and self._execution_paths_table_exists(cursor):
                placeholders = ",".join("?" * len(target_paths))
                q = f"""
                    SELECT DISTINCT execution_id FROM execution_paths
                    WHERE path IN ({placeholders}) AND execution_id != ?
                """
                params: List[Any] = list(target_paths) + [execution_id]
                candidate_ids = [r[0] for r in cursor.execute(q, params).fetchall()]
                if candidate_ids:
                    in_ph = ",".join("?" * len(candidate_ids))
                    query = f"SELECT * FROM executions WHERE execution_id IN ({in_ph})"
                    params_q: List[Any] = list(candidate_ids)
                    if exclude_same_correlation and target.correlation_id:
                        query += " AND (correlation_id IS NULL OR correlation_id != ?)"
                        params_q.append(target.correlation_id)
                    rows = conn.execute(query, params_q).fetchall()

            if not rows:
                query = "SELECT * FROM executions WHERE execution_id != ?"
                params = [execution_id]
                if exclude_same_correlation and target.correlation_id:
                    query += " AND (correlation_id IS NULL OR correlation_id != ?)"
                    params.append(target.correlation_id)
                query += " ORDER BY started_at DESC LIMIT 1000"
                rows = conn.execute(query, params).fetchall()

            engine = SimilarityEngine()
            similarities = []
            for row in rows:
                candidate = ExecutionRecord.from_row(row)
                candidate_paths = self._get_paths_for_execution(
                    conn, candidate.execution_id, candidate.affected_paths
                )
                score = engine.compute_similarity_score(
                    target_execution_id=execution_id,
                    target_error=target.error_message,
                    target_paths=target_paths,
                    target_status=target.status,
                    target_verdict=target.verdict,
                    candidate_execution_id=candidate.execution_id,
                    candidate_error=candidate.error_message,
                    candidate_paths=candidate_paths,
                    candidate_status=candidate.status,
                    candidate_verdict=candidate.verdict
                )
                if score.total_score >= min_similarity:
                    similarities.append((candidate, score))

            similarities.sort(key=lambda x: x[1].total_score, reverse=True)
            return similarities[:limit]
        finally:
            conn.close()

    def find_similar_by_error(
        self,
        error_message: str,
        limit: int = 5,
        min_similarity: float = 0.3
    ) -> List[Tuple[ExecutionRecord, float]]:
        """
        Find executions with similar error messages (Phase 2.4-D).

        Useful for:
        - "Have I seen this error before?"
        - Finding historical fixes for same error

        Args:
            error_message: Target error message
            limit: Maximum results
            min_similarity: Minimum text similarity threshold

        Returns:
            List of (ExecutionRecord, similarity_score) tuples
        """
        # Get all executions with errors
        conn = get_db_connection(self.db_path)
        try:
            rows = conn.execute("""
                SELECT * FROM executions
                WHERE error_message IS NOT NULL
                ORDER BY started_at DESC
                LIMIT 1000
            """).fetchall()

        finally:
            conn.close()

        # Compute text similarity
        engine = SimilarityEngine()
        target_vec = engine.vectorizer.vectorize(error_message)

        similarities: List[Tuple[ExecutionRecord, float]] = []

        for row in rows:
            candidate = ExecutionRecord.from_row(row)

            if not candidate.error_message:
                continue

            candidate_vec = engine.vectorizer.vectorize(candidate.error_message)
            similarity = engine.vectorizer.cosine_similarity(target_vec, candidate_vec)

            if similarity >= min_similarity:
                similarities.append((candidate, similarity))

        # Sort by similarity (descending)
        similarities.sort(key=lambda x: x[1], reverse=True)

        return similarities[:limit]

    def find_similar_by_paths(
        self,
        affected_paths: List[str],
        limit: int = 5,
        min_similarity: float = 0.3
    ) -> List[Tuple[ExecutionRecord, float]]:
        """
        Find executions affecting similar file paths (Phase 2.4-D, 2.5-B execution_paths).

        Useful for:
        - "What else changed these files?"
        - Finding related changes
        """
        from .similarity import PathSimilarity

        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.cursor()
            rows = []
            if affected_paths and self._execution_paths_table_exists(cursor):
                placeholders = ",".join("?" * len(affected_paths))
                q = f"SELECT DISTINCT execution_id FROM execution_paths WHERE path IN ({placeholders})"
                candidate_ids = [r[0] for r in cursor.execute(q, affected_paths).fetchall()]
                if candidate_ids:
                    in_ph = ",".join("?" * len(candidate_ids))
                    rows = conn.execute(
                        f"SELECT * FROM executions WHERE execution_id IN ({in_ph})",
                        list(candidate_ids)
                    ).fetchall()
            if not rows:
                rows = conn.execute("""
                    SELECT * FROM executions
                    WHERE affected_paths IS NOT NULL AND affected_paths != '[]'
                    ORDER BY started_at DESC
                    LIMIT 1000
                """).fetchall()

            similarities = []
            for row in rows:
                candidate = ExecutionRecord.from_row(row)
                candidate_paths = self._get_paths_for_execution(
                    conn, candidate.execution_id, candidate.affected_paths
                )
                if not candidate_paths:
                    continue
                sim = PathSimilarity.jaccard_similarity(affected_paths, candidate_paths)
                if sim >= min_similarity:
                    similarities.append((candidate, sim))
            similarities.sort(key=lambda x: x[1], reverse=True)
            return similarities[:limit]
        finally:
            conn.close()

