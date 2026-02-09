"""
LonelyCat Governance Package

Provides WriteGate governance enforcement for safe code modification.

Components:
- models: Data structures (ChangePlan, ChangeSet, GovernanceDecision)
- writegate: Governance engine (evaluates changes against policies)

Philosophy:
- WriteGate = Judge (evaluates), not Executor (applies)
- ChangePlan + ChangeSet = structured intent + diff
- Verdict = ALLOW / NEED_APPROVAL / DENY
- Audit trail with policy snapshots
"""

from .models import (
    RiskLevel,
    Verdict,
    Operation,
    ChangePlan,
    FileChange,
    ChangeSet,
    GovernanceDecision,
    GovernanceApproval,
    generate_plan_id,
    generate_changeset_id,
    generate_decision_id,
    generate_approval_id
)

from .writegate import (
    WriteGate,
    compute_agent_source_hash,
    compute_projection_hash
)

from .storage import GovernanceStore

from .path_utils import (
    PathViolation,
    CanonicalPathResult,
    canonicalize_path,
    path_policy_check
)

__all__ = [
    # Enums
    "RiskLevel",
    "Verdict",
    "Operation",

    # Models
    "ChangePlan",
    "FileChange",
    "ChangeSet",
    "GovernanceDecision",
    "GovernanceApproval",

    # ID generators
    "generate_plan_id",
    "generate_changeset_id",
    "generate_decision_id",
    "generate_approval_id",

    # WriteGate engine
    "WriteGate",
    "compute_agent_source_hash",
    "compute_projection_hash",

    # Storage
    "GovernanceStore",

    # Path security (Phase 2.1)
    "PathViolation",
    "CanonicalPathResult",
    "canonicalize_path",
    "path_policy_check"
]

__version__ = "1.0.0"
