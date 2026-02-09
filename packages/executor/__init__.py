"""
LonelyCat Host Executor - Phase 2

Philosophy: Safe execution under Planner + WriteGate constraints.

NOT raw power. This is CONTROLLED execution:
- Only applies WriteGate-approved ChangeSets
- Atomic application (all or nothing)
- Auto-verification after changes
- Auto-rollback on failure
- Health check integration

Architecture:
    Planner → ChangePlan + ChangeSet
        ↓
    WriteGate → ALLOW verdict
        ↓
    Executor → Apply changes (safely) ← Phase 2
        ↓
    Verify → Run tests, health checks
        ↓
    Rollback (if failed) → Restore previous state

Key Principle: Executor is constrained by Planner (complete plans) and WriteGate (policy approval).
Without these constraints, Executor = dangerous raw power.
"""

from .executor import (
    HostExecutor,
    ExecutionContext,
    ExecutionResult,
    ExecutionStatus
)

from .file_applier import FileApplier

from .verifier import VerificationRunner

from .rollback import RollbackHandler

from .health import HealthChecker

from .execution_lock import (
    ExecutionLock,
    LockManager,
    LockAcquisitionError
)

from .idempotency import (
    IdempotencyManager,
    ExecutionRecord,
    IdempotencyCheck
)

from .artifacts import (
    ArtifactManager,
    ArtifactConfig,
    replay_execution
)

from .schema import (
    init_executor_db,
    get_db_connection
)

from .storage import (
    ExecutionStore,
    ExecutionRecord,
    StepRecord
)

__all__ = [
    # Core Executor
    "HostExecutor",
    "ExecutionContext",
    "ExecutionResult",
    "ExecutionStatus",

    # Components
    "FileApplier",
    "VerificationRunner",
    "RollbackHandler",
    "HealthChecker",

    # Phase 2.1: Concurrency & Idempotency
    "ExecutionLock",
    "LockManager",
    "LockAcquisitionError",
    "IdempotencyManager",
    "ExecutionRecord",
    "IdempotencyCheck",

    # Phase 2.2-A: Artifact Management
    "ArtifactManager",
    "ArtifactConfig",
    "replay_execution",

    # Phase 2.2-B: Execution History
    "init_executor_db",
    "get_db_connection",
    "ExecutionStore",
    "ExecutionRecord",
    "StepRecord"
]

__version__ = "1.0.0"
