"""
Idempotency Manager - Prevents duplicate executions

Ensures same ChangeSet is not executed multiple times.
Uses execution_id = hash(plan_id + changeset.checksum) to detect duplicates.

Phase 2.1: File-based idempotency cache
"""

from pathlib import Path
import json
import hashlib
from typing import Optional, Dict
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExecutionRecord:
    """Record of a previous execution."""
    execution_id: str
    plan_id: str
    changeset_id: str
    checksum: str
    status: str  # "completed" or "failed"
    executed_at: str
    files_changed: int
    verification_passed: bool
    message: str
    ttl_seconds: int = 3600  # 1 hour default

    def is_expired(self) -> bool:
        """Check if record is expired (TTL)."""
        try:
            executed = datetime.fromisoformat(self.executed_at)
            age = datetime.utcnow() - executed
            return age > timedelta(seconds=self.ttl_seconds)
        except Exception:
            return True  # Treat parse errors as expired

    def is_success(self) -> bool:
        """Check if execution was successful."""
        return self.status == "completed" and self.verification_passed


class IdempotencyManager:
    """
    Manages execution idempotency to prevent duplicate runs.

    Features:
    - Compute execution ID from plan + changeset
    - Check if already executed
    - Cache execution results
    - Support TTL for cache expiration
    - Allow retry on previous failure
    """

    def __init__(
        self,
        workspace_root: Path,
        ttl_seconds: int = 3600,
        allow_retry_on_failure: bool = True
    ):
        """
        Initialize idempotency manager.

        Args:
            workspace_root: Repository root
            ttl_seconds: Cache TTL (default: 1 hour)
            allow_retry_on_failure: Allow retry if previous execution failed
        """
        self.workspace_root = workspace_root
        self.ttl_seconds = ttl_seconds
        self.allow_retry_on_failure = allow_retry_on_failure

        # Cache directory
        self.cache_dir = workspace_root / ".lonelycat" / "executions"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def compute_execution_id(self, plan_id: str, changeset_checksum: str) -> str:
        """
        Compute deterministic execution ID.

        Args:
            plan_id: Plan ID
            changeset_checksum: ChangeSet checksum

        Returns:
            Execution ID (hex string)
        """
        combined = f"{plan_id}:{changeset_checksum}"
        return hashlib.sha256(combined.encode('utf-8')).hexdigest()[:16]

    def check_already_executed(
        self,
        plan_id: str,
        changeset_checksum: str
    ) -> Optional[ExecutionRecord]:
        """
        Check if execution already happened.

        Args:
            plan_id: Plan ID
            changeset_checksum: ChangeSet checksum

        Returns:
            ExecutionRecord if found and not expired, None otherwise
        """
        exec_id = self.compute_execution_id(plan_id, changeset_checksum)
        record = self._load_record(exec_id)

        if not record:
            return None

        # Check expiration
        if record.is_expired():
            logger.info(f"Execution {exec_id} record expired, allowing re-execution")
            self._delete_record(exec_id)
            return None

        # Check if failure and retry allowed
        if not record.is_success() and self.allow_retry_on_failure:
            logger.info(f"Execution {exec_id} failed previously, allowing retry")
            return None

        return record

    def record_execution(
        self,
        execution_id: str,
        plan_id: str,
        changeset_id: str,
        checksum: str,
        status: str,
        files_changed: int,
        verification_passed: bool,
        message: str
    ):
        """
        Record execution result.

        Args:
            execution_id: Execution ID
            plan_id: Plan ID
            changeset_id: ChangeSet ID
            checksum: ChangeSet checksum
            status: "completed" or "failed"
            files_changed: Number of files modified
            verification_passed: Verification result
            message: Result message
        """
        record = ExecutionRecord(
            execution_id=execution_id,
            plan_id=plan_id,
            changeset_id=changeset_id,
            checksum=checksum,
            status=status,
            executed_at=datetime.utcnow().isoformat(),
            files_changed=files_changed,
            verification_passed=verification_passed,
            message=message,
            ttl_seconds=self.ttl_seconds
        )

        self._save_record(record)
        logger.info(f"Recorded execution {execution_id} with status {status}")

    def get_execution_history(self, limit: int = 10) -> list[ExecutionRecord]:
        """
        Get recent execution history.

        Args:
            limit: Max number of records to return

        Returns:
            List of ExecutionRecord, newest first
        """
        records = []

        # Load all records
        for record_file in self.cache_dir.glob("exec_*.json"):
            try:
                record = self._load_record_from_file(record_file)
                if record and not record.is_expired():
                    records.append(record)
            except Exception as e:
                logger.warning(f"Failed to load record {record_file}: {e}")

        # Sort by executed_at (newest first)
        records.sort(key=lambda r: r.executed_at, reverse=True)

        return records[:limit]

    def clean_expired_records(self) -> int:
        """
        Clean up expired execution records.

        Returns:
            Number of records deleted
        """
        deleted = 0

        for record_file in self.cache_dir.glob("exec_*.json"):
            try:
                record = self._load_record_from_file(record_file)
                if record and record.is_expired():
                    record_file.unlink()
                    deleted += 1
                    logger.debug(f"Deleted expired record: {record.execution_id}")
            except Exception as e:
                logger.warning(f"Failed to clean record {record_file}: {e}")

        if deleted > 0:
            logger.info(f"Cleaned {deleted} expired execution records")

        return deleted

    def _get_record_path(self, execution_id: str) -> Path:
        """Get path to record file."""
        return self.cache_dir / f"exec_{execution_id}.json"

    def _save_record(self, record: ExecutionRecord):
        """Save execution record to disk."""
        record_path = self._get_record_path(record.execution_id)

        try:
            with open(record_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(record), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save execution record: {e}")

    def _load_record(self, execution_id: str) -> Optional[ExecutionRecord]:
        """Load execution record from disk."""
        record_path = self._get_record_path(execution_id)
        return self._load_record_from_file(record_path)

    def _load_record_from_file(self, record_path: Path) -> Optional[ExecutionRecord]:
        """Load execution record from file path."""
        if not record_path.exists():
            return None

        try:
            with open(record_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ExecutionRecord(**data)
        except Exception as e:
            logger.error(f"Failed to load execution record from {record_path}: {e}")
            return None

    def _delete_record(self, execution_id: str):
        """Delete execution record."""
        record_path = self._get_record_path(execution_id)
        if record_path.exists():
            record_path.unlink()


class IdempotencyCheck:
    """
    Context manager for idempotency check.

    Usage:
        idem = IdempotencyManager(workspace)

        with IdempotencyCheck(idem, plan_id, checksum) as check:
            if check.already_executed:
                return check.previous_result

            # Execute
            result = execute_changeset()
            check.record_result(result)
    """

    def __init__(
        self,
        manager: IdempotencyManager,
        plan_id: str,
        changeset_checksum: str
    ):
        self.manager = manager
        self.plan_id = plan_id
        self.changeset_checksum = changeset_checksum
        self.execution_id = manager.compute_execution_id(plan_id, changeset_checksum)
        self.previous_record: Optional[ExecutionRecord] = None
        self.already_executed = False

    def __enter__(self):
        """Check if already executed."""
        self.previous_record = self.manager.check_already_executed(
            self.plan_id,
            self.changeset_checksum
        )
        self.already_executed = self.previous_record is not None

        if self.already_executed:
            logger.info(
                f"Execution {self.execution_id} already completed: "
                f"{self.previous_record.message}"
            )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """No cleanup needed."""
        return False

    def record_result(
        self,
        changeset_id: str,
        status: str,
        files_changed: int,
        verification_passed: bool,
        message: str
    ):
        """Record execution result."""
        self.manager.record_execution(
            execution_id=self.execution_id,
            plan_id=self.plan_id,
            changeset_id=changeset_id,
            checksum=self.changeset_checksum,
            status=status,
            files_changed=files_changed,
            verification_passed=verification_passed,
            message=message
        )
