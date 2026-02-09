"""
Host Executor - Core Execution Engine

Safely applies WriteGate-approved ChangeSets to the host filesystem.

Flow:
    1. Validate approval (WriteGate ALLOW or human approval)
    2. Create backup (for rollback)
    3. Apply changes atomically
    4. Run verification
    5. Run health checks
    6. Rollback if any step fails

Safety:
- Only executes approved ChangeSets
- Atomic application (all or nothing)
- Auto-rollback on failure
- Detailed audit trail
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
import shutil
import tempfile

# Import governance models
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from governance import (
    ChangeSet,
    ChangePlan,
    GovernanceDecision,
    Verdict
)


class ExecutionStatus(Enum):
    """Execution status."""
    PENDING = "pending"
    VALIDATING = "validating"
    BACKING_UP = "backing_up"
    APPLYING = "applying"
    VERIFYING = "verifying"
    HEALTH_CHECKING = "health_checking"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class ExecutionContext:
    """Context for an execution run."""
    id: str
    plan_id: str
    changeset_id: str
    decision_id: str

    # Status
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None

    # Paths
    backup_dir: Optional[Path] = None
    affected_files: List[str] = field(default_factory=list)

    # Results
    applied_changes: List[str] = field(default_factory=list)
    verification_results: Dict = field(default_factory=dict)
    health_check_results: Dict = field(default_factory=dict)

    # Error handling
    error_message: Optional[str] = None
    rolled_back: bool = False

    # History
    status_history: List[Dict] = field(default_factory=list)

    def update_status(self, new_status: ExecutionStatus, message: str = ""):
        """Update execution status and record in history."""
        self.status_history.append({
            "status": new_status.value,
            "message": message,
            "timestamp": datetime.utcnow().isoformat()
        })
        self.status = new_status


@dataclass
class ExecutionResult:
    """Result of an execution."""
    context: ExecutionContext
    success: bool
    message: str

    # Detailed results
    files_changed: int
    verification_passed: bool
    health_checks_passed: bool

    # Timing
    duration_seconds: float

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "execution_id": self.context.id,
            "plan_id": self.context.plan_id,
            "success": self.success,
            "message": self.message,
            "status": self.context.status.value,
            "files_changed": self.files_changed,
            "verification_passed": self.verification_passed,
            "health_checks_passed": self.health_checks_passed,
            "duration_seconds": self.duration_seconds,
            "started_at": self.context.started_at.isoformat(),
            "completed_at": self.context.completed_at.isoformat() if self.context.completed_at else None,
            "rolled_back": self.context.rolled_back,
            "error_message": self.context.error_message
        }


class HostExecutor:
    """
    Main execution engine.

    Coordinates:
    - FileApplier: Applies file changes
    - VerificationRunner: Runs verification plans
    - RollbackHandler: Handles rollback on failure
    - HealthChecker: Runs health checks
    """

    def __init__(
        self,
        workspace_root: Path,
        dry_run: bool = False,
        use_locking: bool = True,
        use_idempotency: bool = True,
        hooks: Optional[dict] = None
    ):
        """
        Initialize executor.

        Args:
            workspace_root: Root directory for operations
            dry_run: If True, simulate execution without actual changes
            use_locking: If True, enforce execution lock (default: True)
            use_idempotency: If True, check for duplicate execution (default: True)
            hooks: Optional hooks for testing (before_do_execute, after_do_execute)
        """
        # Normalize workspace_root to avoid path inconsistencies (Windows case/slash)
        self.workspace_root = Path(workspace_root).resolve()
        self.dry_run = dry_run
        self.use_locking = use_locking
        self.use_idempotency = use_idempotency

        # Test hooks (for observability in concurrent tests)
        self.hooks = hooks or {}

        # Will be imported when needed to avoid circular dependencies
        self.file_applier = None
        self.verifier = None
        self.rollback_handler = None
        self.health_checker = None

        # Phase 2.1: Locking and idempotency
        self.lock_manager = None
        self.idempotency_manager = None

        if self.use_locking:
            from .execution_lock import LockManager
            self.lock_manager = LockManager(workspace_root, timeout_seconds=600)

        if self.use_idempotency:
            from .idempotency import IdempotencyManager
            self.idempotency_manager = IdempotencyManager(
                workspace_root,
                ttl_seconds=3600,
                allow_retry_on_failure=True
            )

        # Phase 2.2: Artifact management
        from .artifacts import ArtifactManager
        self.artifact_manager = ArtifactManager(workspace_root)

        # Phase 2.2-B: Execution history storage
        from .storage import ExecutionStore
        self.execution_store = ExecutionStore(workspace_root)

    def execute(
        self,
        plan: ChangePlan,
        changeset: ChangeSet,
        decision: GovernanceDecision
    ) -> ExecutionResult:
        """
        Execute a ChangeSet.

        This is the main entry point for Phase 2 execution.

        Args:
            plan: ChangePlan (from Planner)
            changeset: ChangeSet (from Planner)
            decision: GovernanceDecision (from WriteGate)

        Returns:
            ExecutionResult with success/failure info

        Raises:
            ValueError: If decision is not approved
        """
        # Generate execution ID
        import uuid
        exec_id = f"exec_{uuid.uuid4().hex[:12]}"

        # PHASE 2.1: Acquire lock FIRST (widest scope)
        # Lock must cover: idempotency check, execution, and result recording
        if self.use_locking and self.lock_manager:
            with self.lock_manager.lock_execution(exec_id, plan.id):
                return self._execute_with_idempotency(exec_id, plan, changeset, decision)
        else:
            return self._execute_with_idempotency(exec_id, plan, changeset, decision)

    def _execute_with_idempotency(
        self,
        exec_id: str,
        plan: ChangePlan,
        changeset: ChangeSet,
        decision: GovernanceDecision
    ) -> ExecutionResult:
        """
        Execute with idempotency check.

        IMPORTANT: This method should be called INSIDE the execution lock
        to ensure atomicity of idempotency check + execution + record.
        """
        # PHASE 2.1: Check idempotency (prevent duplicate execution)
        # This happens INSIDE the lock to ensure atomicity
        if self.use_idempotency and self.idempotency_manager:
            from .idempotency import IdempotencyCheck

            with IdempotencyCheck(
                self.idempotency_manager,
                plan.id,
                changeset.checksum
            ) as idem_check:
                if idem_check.already_executed:
                    # Return cached result
                    prev = idem_check.previous_record
                    return self._create_cached_result(
                        exec_id=idem_check.execution_id,
                        plan_id=plan.id,
                        changeset_id=changeset.id,
                        decision_id=decision.id,
                        previous_record=prev
                    )

                # Not executed yet - proceed with execution
                result = self._do_execute(exec_id, plan, changeset, decision)

                # Record execution result (INSIDE lock)
                idem_check.record_result(
                    changeset_id=changeset.id,
                    status="completed" if result.success else "failed",
                    files_changed=result.files_changed,
                    verification_passed=result.verification_passed,
                    message=result.message
                )

                return result

        else:
            # No idempotency check - just execute
            return self._do_execute(exec_id, plan, changeset, decision)

    def _do_execute(
        self,
        exec_id: str,
        plan: ChangePlan,
        changeset: ChangeSet,
        decision: GovernanceDecision
    ) -> ExecutionResult:
        """
        Internal execute method (actual execution logic).

        Separated from execute() to support locking/idempotency wrappers.
        """
        # Test hook: before_do_execute (for concurrent test observability)
        if "before_do_execute" in self.hooks:
            self.hooks["before_do_execute"](exec_id, plan.id)

        # Create context
        context = ExecutionContext(
            id=exec_id,
            plan_id=plan.id,
            changeset_id=changeset.id,
            decision_id=decision.id,
            status=ExecutionStatus.PENDING,
            started_at=datetime.utcnow()
        )

        start_time = datetime.utcnow()

        # Phase 2.2-A: Create artifact directory and write initial JSONs
        if not self.dry_run:
            self.artifact_manager.create_execution_dir(exec_id)
            self.artifact_manager.write_plan(exec_id, plan)
            self.artifact_manager.write_changeset(exec_id, changeset)
            self.artifact_manager.write_decision(exec_id, decision)

            # Phase 2.2-B: Record execution start in database
            artifact_path = str(self.artifact_manager.get_execution_dir(exec_id))
            self.execution_store.record_execution_start(
                execution_id=exec_id,
                plan_id=plan.id,
                changeset_id=changeset.id,
                decision_id=decision.id,
                checksum=changeset.checksum,
                verdict=decision.verdict.value,
                risk_level=decision.risk_level_effective.value,
                affected_paths=plan.affected_paths,
                artifact_path=artifact_path
            )

        try:
            # Step 1: Validate approval
            context.update_status(ExecutionStatus.VALIDATING, "Validating approval")
            self._log_step(exec_id, 1, "validate", "Starting approval validation")
            self._validate_approval(decision)
            self._log_step(exec_id, 1, "validate", "Approval validated successfully")

            # Step 2: Verify changeset integrity
            self._log_step(exec_id, 2, "checksum", f"Verifying checksum: {changeset.checksum}")
            if not changeset.verify_checksum():
                raise ValueError("ChangeSet checksum verification failed (possible tampering)")
            self._log_step(exec_id, 2, "checksum", "Checksum verified successfully")

            # Step 3: Create backup
            context.update_status(ExecutionStatus.BACKING_UP, "Creating backup")
            self._log_step(exec_id, 3, "backup", f"Creating backup for {len(changeset.changes)} files")
            context.backup_dir = self._create_backup(changeset)
            self._log_step(exec_id, 3, "backup", f"Backup created at {context.backup_dir}")

            # Phase 2.2-A: Link backup to artifact
            if not self.dry_run and context.backup_dir:
                self.artifact_manager.link_backup(exec_id, context.backup_dir)

            # Step 4: Apply changes
            context.update_status(ExecutionStatus.APPLYING, "Applying changes")
            self._log_step(exec_id, 4, "apply", f"Applying {len(changeset.changes)} file changes")
            applied = self._apply_changes(changeset, context)
            context.applied_changes = applied
            self._log_step(exec_id, 4, "apply", f"Successfully applied changes to {len(applied)} files")

            # Step 5: Run verification
            context.update_status(ExecutionStatus.VERIFYING, "Running verification")
            self._log_step(exec_id, 5, "verify", f"Running verification: {plan.verification_plan}")
            verification_results = self._run_verification(plan, context)
            context.verification_results = verification_results

            if not verification_results.get("passed", False):
                self._log_step(exec_id, 5, "verify", f"FAILED: {verification_results.get('message')}")
                raise Exception(f"Verification failed: {verification_results.get('message')}")
            self._log_step(exec_id, 5, "verify", "Verification passed")

            # Step 6: Run health checks
            context.update_status(ExecutionStatus.HEALTH_CHECKING, "Running health checks")
            self._log_step(exec_id, 6, "health", f"Running {len(plan.health_checks)} health checks")
            health_results = self._run_health_checks(plan, context)
            context.health_check_results = health_results

            if not health_results.get("passed", False):
                self._log_step(exec_id, 6, "health", f"FAILED: {health_results.get('message')}")
                raise Exception(f"Health checks failed: {health_results.get('message')}")
            self._log_step(exec_id, 6, "health", "All health checks passed")

            # Success!
            context.update_status(ExecutionStatus.COMPLETED, "Execution completed successfully")
            context.completed_at = datetime.utcnow()

            duration = (context.completed_at - start_time).total_seconds()

            result = ExecutionResult(
                context=context,
                success=True,
                message="ChangeSet applied successfully",
                files_changed=len(context.applied_changes),
                verification_passed=True,
                health_checks_passed=True,
                duration_seconds=duration
            )

            # Phase 2.2-A: Write final execution.json
            if not self.dry_run:
                self.artifact_manager.write_execution(exec_id, result.to_dict())
                self._log_step(exec_id, 7, "finalize", f"Execution completed in {duration:.2f}s")

                # Phase 2.2-B: Record execution end in database
                self.execution_store.record_execution_end(
                    execution_id=exec_id,
                    status="completed",
                    duration_seconds=duration,
                    files_changed=len(context.applied_changes),
                    verification_passed=True,
                    health_checks_passed=True,
                    rolled_back=False
                )

            # Test hook: after_do_execute
            if "after_do_execute" in self.hooks:
                self.hooks["after_do_execute"](exec_id, plan.id)

            return result

        except Exception as e:
            # Failure - rollback
            context.error_message = str(e)
            context.update_status(ExecutionStatus.FAILED, f"Execution failed: {e}")
            self._log_step(exec_id, 99, "error", f"ERROR: {e}")

            # Attempt rollback
            if context.backup_dir:
                try:
                    self._log_step(exec_id, 98, "rollback", f"Starting rollback from {context.backup_dir}")
                    self._rollback(context)
                    context.rolled_back = True
                    context.update_status(ExecutionStatus.ROLLED_BACK, "Changes rolled back")
                    self._log_step(exec_id, 98, "rollback", "Rollback completed successfully")
                except Exception as rollback_error:
                    context.error_message += f"; Rollback failed: {rollback_error}"
                    self._log_step(exec_id, 98, "rollback", f"ROLLBACK FAILED: {rollback_error}")

            context.completed_at = datetime.utcnow()
            duration = (context.completed_at - start_time).total_seconds()

            result = ExecutionResult(
                context=context,
                success=False,
                message=f"Execution failed: {e}",
                files_changed=len(context.applied_changes),
                verification_passed=False,
                health_checks_passed=False,
                duration_seconds=duration
            )

            # Phase 2.2-A: Write final execution.json (even on failure)
            if not self.dry_run:
                self.artifact_manager.write_execution(exec_id, result.to_dict())
                self._log_step(exec_id, 99, "error", f"Execution failed after {duration:.2f}s")

                # Phase 2.2-B: Record execution end in database (failure)
                self.execution_store.record_execution_end(
                    execution_id=exec_id,
                    status=context.status.value,
                    duration_seconds=duration,
                    files_changed=len(context.applied_changes),
                    verification_passed=False,
                    health_checks_passed=False,
                    rolled_back=context.rolled_back,
                    error_message=context.error_message,
                    error_step=context.status.value
                )

            # Test hook: after_do_execute (even on failure)
            if "after_do_execute" in self.hooks:
                self.hooks["after_do_execute"](exec_id, plan.id)

            return result

    def _create_cached_result(
        self,
        exec_id: str,
        plan_id: str,
        changeset_id: str,
        decision_id: str,
        previous_record
    ) -> ExecutionResult:
        """
        Create ExecutionResult from cached previous execution.

        Args:
            exec_id: Execution ID
            plan_id: Plan ID
            changeset_id: ChangeSet ID
            decision_id: Decision ID
            previous_record: ExecutionRecord from idempotency cache

        Returns:
            ExecutionResult with cached data
        """
        context = ExecutionContext(
            id=exec_id,
            plan_id=plan_id,
            changeset_id=changeset_id,
            decision_id=decision_id,
            status=ExecutionStatus.COMPLETED if previous_record.is_success() else ExecutionStatus.FAILED,
            started_at=datetime.fromisoformat(previous_record.executed_at),
            completed_at=datetime.fromisoformat(previous_record.executed_at)
        )

        return ExecutionResult(
            context=context,
            success=previous_record.is_success(),
            message=f"[CACHED] {previous_record.message}",
            files_changed=previous_record.files_changed,
            verification_passed=previous_record.verification_passed,
            health_checks_passed=True,  # Assume yes for cached
            duration_seconds=0.0  # Cached, no duration
        )

    def _validate_approval(self, decision: GovernanceDecision):
        """
        Validate that ChangeSet has been approved.

        Args:
            decision: GovernanceDecision from WriteGate

        Raises:
            ValueError: If not approved
        """
        if decision.verdict != Verdict.ALLOW:
            raise ValueError(
                f"Cannot execute: Decision verdict is {decision.verdict.value}, "
                f"must be ALLOW. Reasons: {', '.join(decision.reasons)}"
            )

    def _create_backup(self, changeset: ChangeSet) -> Path:
        """
        Create backup of files to be changed.

        Args:
            changeset: ChangeSet with file changes

        Returns:
            Path to backup directory
        """
        if self.dry_run:
            return Path(tempfile.mkdtemp(prefix="dryrun_backup_"))

        # Create temp backup directory
        backup_dir = Path(tempfile.mkdtemp(prefix="lonelycat_backup_"))

        for change in changeset.changes:
            file_path = self.workspace_root / change.path

            if file_path.exists():
                # Backup existing file
                backup_path = backup_dir / change.path
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, backup_path)

        return backup_dir

    def _apply_changes(self, changeset: ChangeSet, context: ExecutionContext) -> List[str]:
        """
        Apply file changes from ChangeSet.

        Args:
            changeset: ChangeSet to apply
            context: Execution context

        Returns:
            List of applied file paths
        """
        if self.file_applier is None:
            from .file_applier import FileApplier
            self.file_applier = FileApplier(self.workspace_root, self.dry_run)

        return self.file_applier.apply_changeset(changeset)

    def _run_verification(self, plan: ChangePlan, context: ExecutionContext) -> Dict:
        """
        Run verification plan.

        Args:
            plan: ChangePlan with verification_plan
            context: Execution context

        Returns:
            dict with verification results
        """
        if self.verifier is None:
            from .verifier import VerificationRunner
            self.verifier = VerificationRunner(self.workspace_root, self.dry_run)

        return self.verifier.run_verification(plan.verification_plan, context)

    def _run_health_checks(self, plan: ChangePlan, context: ExecutionContext) -> Dict:
        """
        Run health checks.

        Args:
            plan: ChangePlan with health_checks
            context: Execution context

        Returns:
            dict with health check results
        """
        if self.health_checker is None:
            from .health import HealthChecker
            self.health_checker = HealthChecker(self.workspace_root, self.dry_run)

        return self.health_checker.run_health_checks(plan.health_checks, context)

    def _rollback(self, context: ExecutionContext):
        """
        Rollback changes using backup.

        Args:
            context: Execution context with backup_dir

        Raises:
            Exception: If rollback fails
        """
        if self.rollback_handler is None:
            from .rollback import RollbackHandler
            self.rollback_handler = RollbackHandler(self.workspace_root, self.dry_run)

        self.rollback_handler.rollback(context)

    def _log_step(self, execution_id: str, step_num: int, step_name: str, message: str):
        """
        Log a step to artifact (Phase 2.2-A).

        Args:
            execution_id: Execution ID
            step_num: Step number
            step_name: Step name
            message: Log message
        """
        if not self.dry_run:
            self.artifact_manager.append_step_log(execution_id, step_num, step_name, message)

    def _track_step(self, execution_id: str, step_num: int, step_name: str):
        """
        Context manager for tracking step timing in database (Phase 2.2-B).

        Args:
            execution_id: Execution ID
            step_num: Step number
            step_name: Step name

        Usage:
            with self._track_step(exec_id, 1, "validate"):
                # Do work
                pass
        """
        from contextlib import contextmanager
        from time import time

        @contextmanager
        def step_tracker():
            step_id = None
            start_time = time()

            if not self.dry_run:
                # Record step start in database
                log_ref = f"steps/{step_num:02d}_{step_name}.log"
                step_id = self.execution_store.record_step_start(
                    execution_id=execution_id,
                    step_num=step_num,
                    step_name=step_name,
                    log_ref=log_ref
                )

            try:
                yield
                # Step succeeded
                if not self.dry_run and step_id:
                    duration = time() - start_time
                    self.execution_store.record_step_end(
                        step_id=step_id,
                        status="completed",
                        duration_seconds=duration
                    )
            except Exception as e:
                # Step failed
                if not self.dry_run and step_id:
                    duration = time() - start_time
                    self.execution_store.record_step_end(
                        step_id=step_id,
                        status="failed",
                        duration_seconds=duration,
                        error_code=type(e).__name__,
                        error_message=str(e)
                    )
                raise

        return step_tracker()


def generate_execution_id() -> str:
    """Generate unique execution ID."""
    import uuid
    return f"exec_{uuid.uuid4().hex[:12]}"
