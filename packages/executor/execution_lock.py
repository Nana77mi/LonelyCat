"""
Execution Lock - Prevents concurrent executions

Provides repository-level mutex to ensure only one execution happens at a time.
This prevents:
- Concurrent file modifications causing corruption
- Backup/rollback interference between executions
- Race conditions in verification

Phase 2.1: Cross-platform file-based locking
"""

from pathlib import Path
import time
import os
import json
from typing import Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class LockAcquisitionError(Exception):
    """Raised when lock cannot be acquired."""
    pass


class ExecutionLock:
    """
    Repository-level execution lock using file-based mutex.

    Uses atomic file creation for cross-platform locking.
    Lock file contains metadata about current execution.
    """

    def __init__(
        self,
        workspace_root: Path,
        timeout_seconds: int = 600,
        stale_threshold_seconds: int = 7200
    ):
        """
        Initialize execution lock.

        Args:
            workspace_root: Repository root directory
            timeout_seconds: Max time to wait for lock (default: 10 minutes)
            stale_threshold_seconds: Consider lock stale after this time (default: 2 hours)
        """
        # Normalize workspace_root to avoid path inconsistencies (Windows case/slash)
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout_seconds = timeout_seconds
        self.stale_threshold_seconds = stale_threshold_seconds

        # Lock directory
        self.lock_dir = self.workspace_root / ".lonelycat" / "locks"
        self.lock_dir.mkdir(parents=True, exist_ok=True)

        # Lock file
        self.lock_file = self.lock_dir / "execution.lock"

        # Current lock metadata
        self.lock_metadata = None

    def acquire(self, execution_id: str, plan_id: str) -> bool:
        """
        Acquire execution lock.

        Args:
            execution_id: Current execution ID
            plan_id: Current plan ID

        Returns:
            True if acquired, False otherwise

        Raises:
            LockAcquisitionError: If timeout or cannot acquire
        """
        start_time = time.time()

        while True:
            # Try to acquire lock
            if self._try_acquire(execution_id, plan_id):
                logger.info(f"Lock acquired for execution {execution_id}")
                return True

            # Check timeout
            elapsed = time.time() - start_time
            if elapsed >= self.timeout_seconds:
                # Try to clean up stale lock
                if self._is_stale():
                    logger.warning("Detected stale lock, attempting cleanup")
                    if self._force_release():
                        # Try one more time
                        if self._try_acquire(execution_id, plan_id):
                            logger.info(f"Lock acquired after stale cleanup for execution {execution_id}")
                            return True

                # Could not acquire
                lock_info = self._read_lock()
                raise LockAcquisitionError(
                    f"Could not acquire lock after {self.timeout_seconds}s. "
                    f"Lock held by: {lock_info.get('execution_id', 'unknown')}"
                )

            # Wait and retry
            time.sleep(1)

    def release(self) -> bool:
        """
        Release execution lock.

        Returns:
            True if released, False if lock not held
        """
        if not self.lock_file.exists():
            logger.warning("Attempted to release lock but lock file does not exist")
            return False

        # Verify we hold the lock
        lock_data = self._read_lock()
        if lock_data and lock_data.get("execution_id") != self.lock_metadata.get("execution_id"):
            logger.error(
                f"Lock ownership mismatch: "
                f"expected {self.lock_metadata.get('execution_id')}, "
                f"got {lock_data.get('execution_id')}"
            )
            return False

        # Release
        try:
            self.lock_file.unlink()
            logger.info(f"Lock released for execution {self.lock_metadata.get('execution_id')}")
            self.lock_metadata = None
            return True
        except Exception as e:
            logger.error(f"Failed to release lock: {e}")
            return False

    def is_locked(self) -> bool:
        """Check if execution is currently locked."""
        return self.lock_file.exists()

    def get_lock_info(self) -> Optional[dict]:
        """
        Get information about current lock holder.

        Returns:
            dict with lock metadata, or None if not locked
        """
        if not self.is_locked():
            return None
        return self._read_lock()

    def _try_acquire(self, execution_id: str, plan_id: str) -> bool:
        """
        Attempt to acquire lock atomically.

        Uses O_CREAT | O_EXCL for atomic creation.

        Returns:
            True if acquired, False if already locked
        """
        if self.lock_file.exists():
            return False

        try:
            # Atomic create (fails if exists)
            # Use os.open with O_CREAT | O_EXCL for atomicity
            fd = os.open(
                str(self.lock_file),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644
            )

            # Write lock metadata
            metadata = {
                "execution_id": execution_id,
                "plan_id": plan_id,
                "acquired_at": datetime.utcnow().isoformat(),
                "pid": os.getpid(),
                "hostname": os.environ.get("COMPUTERNAME", os.environ.get("HOSTNAME", "unknown"))
            }

            os.write(fd, json.dumps(metadata, indent=2).encode('utf-8'))
            os.close(fd)

            self.lock_metadata = metadata
            return True

        except FileExistsError:
            # Lock already held
            return False
        except Exception as e:
            logger.error(f"Failed to acquire lock: {e}")
            return False

    def _read_lock(self) -> Optional[dict]:
        """
        Read lock metadata from file.

        Returns:
            dict with metadata, or None if cannot read
        """
        if not self.lock_file.exists():
            return None

        try:
            with open(self.lock_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read lock file: {e}")
            return None

    def _is_stale(self) -> bool:
        """
        Check if current lock is stale (held too long).

        Conservative strategy: Only consider stale if:
        1. Lock age > threshold
        2. AND cannot confirm process is alive

        Returns:
            True if stale, False otherwise
        """
        lock_data = self._read_lock()
        if not lock_data:
            return False

        try:
            acquired_at = datetime.fromisoformat(lock_data["acquired_at"])
            age = datetime.utcnow() - acquired_at

            # First check: is it old enough?
            if age <= timedelta(seconds=self.stale_threshold_seconds):
                return False  # Not old enough

            # Second check: can we confirm the process is dead?
            pid = lock_data.get("pid")
            if pid:
                is_alive = self._is_process_alive(pid)
                if is_alive:
                    logger.warning(
                        f"Lock is old ({age.total_seconds():.0f}s) but process {pid} is still alive"
                    )
                    return False  # Process still alive, not stale

            # Old AND (no PID OR process dead) → stale
            logger.warning(
                f"Lock is stale: acquired {age.total_seconds():.0f}s ago "
                f"(threshold: {self.stale_threshold_seconds}s), "
                f"process {pid} not running"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to check stale lock: {e}")
            return False  # Conservative: don't clean if uncertain

    def _is_process_alive(self, pid: int) -> bool:
        """
        Check if process is alive (best effort).

        Returns:
            True if alive, False if dead or unknown
        """
        import platform

        try:
            if platform.system() == "Windows":
                # Windows: use tasklist
                import subprocess
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                # If PID appears in output, process is alive
                return str(pid) in result.stdout
            else:
                # Unix: send signal 0
                import os
                os.kill(pid, 0)
                return True  # No exception = alive
        except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError, OSError):
            return False  # Process not found or timeout
        except Exception as e:
            logger.warning(f"Could not check if PID {pid} is alive: {e}")
            return True  # Conservative: assume alive if check fails

    def _force_release(self) -> bool:
        """
        Force release stale lock.

        WARNING: Only call after confirming lock is stale.

        Returns:
            True if released, False otherwise
        """
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
                logger.warning("Force released stale lock")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to force release lock: {e}")
            return False

    def __enter__(self):
        """Context manager entry - acquire lock."""
        # Note: acquire() needs execution_id/plan_id, so this is a placeholder
        # Use acquire() explicitly instead of context manager
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - release lock."""
        if self.lock_metadata:
            self.release()
        return False


class LockManager:
    """
    High-level lock manager with convenience methods.

    Usage:
        lock_mgr = LockManager(workspace_root)

        with lock_mgr.lock_execution(exec_id, plan_id):
            # Execute changeset
            pass
    """

    def __init__(self, workspace_root: Path, timeout_seconds: int = 600):
        """
        Initialize lock manager.

        Args:
            workspace_root: Repository root
            timeout_seconds: Lock acquisition timeout
        """
        self.workspace_root = workspace_root
        self.timeout_seconds = timeout_seconds

    def lock_execution(self, execution_id: str, plan_id: str):
        """
        Get execution lock context manager.

        Args:
            execution_id: Execution ID
            plan_id: Plan ID

        Returns:
            Context manager that acquires/releases lock

        Usage:
            with lock_mgr.lock_execution(exec_id, plan_id):
                apply_changes()
        """
        return ExecutionLockContext(
            self.workspace_root,
            execution_id,
            plan_id,
            self.timeout_seconds
        )

    def is_locked(self) -> bool:
        """Check if execution is currently locked."""
        lock = ExecutionLock(self.workspace_root)
        return lock.is_locked()

    def get_lock_info(self) -> Optional[dict]:
        """Get current lock holder information."""
        lock = ExecutionLock(self.workspace_root)
        return lock.get_lock_info()


class ExecutionLockContext:
    """Context manager for execution lock."""

    def __init__(
        self,
        workspace_root: Path,
        execution_id: str,
        plan_id: str,
        timeout_seconds: int
    ):
        self.lock = ExecutionLock(workspace_root, timeout_seconds)
        self.execution_id = execution_id
        self.plan_id = plan_id

    def __enter__(self):
        """Acquire lock on entry."""
        self.lock.acquire(self.execution_id, self.plan_id)
        return self.lock

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release lock on exit."""
        self.lock.release()
        return False
