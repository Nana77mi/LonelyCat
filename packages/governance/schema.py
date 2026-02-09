"""
Database Schema for WriteGate Governance System

Tables:
- governance_plans: ChangePlan records
- governance_changesets: ChangeSet records (structured diffs)
- governance_decisions: GovernanceDecision records (WriteGate verdicts)
- governance_approvals: GovernanceApproval records (human approvals)

Philosophy:
- All governance artifacts persisted for audit trail
- Policy snapshots enable replay debugging
- Immutable records (append-only, no updates)
"""

import sqlite3
from pathlib import Path
from typing import Optional


# Table schemas (SQLite)

GOVERNANCE_PLANS_TABLE = """
CREATE TABLE IF NOT EXISTS governance_plans (
    id TEXT PRIMARY KEY,

    -- Core Intent
    intent TEXT NOT NULL,
    objective TEXT NOT NULL,
    rationale TEXT NOT NULL,

    -- Scope
    affected_paths TEXT NOT NULL,  -- JSON array
    dependencies TEXT NOT NULL,    -- JSON array

    -- Risk Assessment (SPLIT to prevent LLM cheating)
    risk_level_proposed TEXT NOT NULL,  -- 'low'|'medium'|'high'|'critical'
    risk_level_effective TEXT,          -- Set by WriteGate (may escalate)
    risk_escalation_reason TEXT,

    -- Verification Plans
    rollback_plan TEXT NOT NULL,
    verification_plan TEXT NOT NULL,
    health_checks TEXT NOT NULL,    -- JSON array

    -- Governance References
    policy_refs TEXT NOT NULL,      -- JSON array

    -- Metadata
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,       -- ISO 8601
    confidence REAL NOT NULL,
    run_id TEXT,

    -- Full JSON snapshot (for replay)
    full_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_plans_created_at ON governance_plans(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_plans_created_by ON governance_plans(created_by);
CREATE INDEX IF NOT EXISTS idx_plans_risk_effective ON governance_plans(risk_level_effective);
"""


GOVERNANCE_CHANGESETS_TABLE = """
CREATE TABLE IF NOT EXISTS governance_changesets (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,

    -- Changes (structured diffs)
    changes TEXT NOT NULL,      -- JSON array of FileChange objects
    checksum TEXT NOT NULL,     -- SHA256(changes) - tamper detection

    -- Metadata
    generated_by TEXT NOT NULL,
    generated_at TEXT NOT NULL, -- ISO 8601

    -- Full JSON snapshot
    full_json TEXT NOT NULL,

    FOREIGN KEY (plan_id) REFERENCES governance_plans(id)
);

CREATE INDEX IF NOT EXISTS idx_changesets_plan_id ON governance_changesets(plan_id);
CREATE INDEX IF NOT EXISTS idx_changesets_generated_at ON governance_changesets(generated_at DESC);
"""


GOVERNANCE_DECISIONS_TABLE = """
CREATE TABLE IF NOT EXISTS governance_decisions (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    changeset_id TEXT NOT NULL,

    -- Verdict
    verdict TEXT NOT NULL,              -- 'allow'|'need_approval'|'deny'
    reasons TEXT NOT NULL,              -- JSON array
    violated_policies TEXT NOT NULL,    -- JSON array
    required_actions TEXT NOT NULL,     -- JSON array

    -- Effective Risk (computed by WriteGate)
    risk_level_effective TEXT NOT NULL,

    -- Audit Metadata (CRITICAL for debugging/replay)
    policy_snapshot_hash TEXT NOT NULL,   -- Hash of agent/policies/default.yaml
    agent_source_hash TEXT NOT NULL,      -- Hash of agent/ directory
    projection_hash TEXT,                 -- Hash of AGENTS.md, CLAUDE.md (optional)
    writegate_version TEXT NOT NULL,      -- WriteGate engine version

    evaluated_at TEXT NOT NULL,           -- ISO 8601
    evaluator TEXT NOT NULL,              -- 'writegate_engine'

    -- Full JSON snapshot
    full_json TEXT NOT NULL,

    FOREIGN KEY (plan_id) REFERENCES governance_plans(id),
    FOREIGN KEY (changeset_id) REFERENCES governance_changesets(id)
);

CREATE INDEX IF NOT EXISTS idx_decisions_plan_id ON governance_decisions(plan_id);
CREATE INDEX IF NOT EXISTS idx_decisions_verdict ON governance_decisions(verdict);
CREATE INDEX IF NOT EXISTS idx_decisions_evaluated_at ON governance_decisions(evaluated_at DESC);
"""


GOVERNANCE_APPROVALS_TABLE = """
CREATE TABLE IF NOT EXISTS governance_approvals (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,

    -- Approval
    approved_by TEXT NOT NULL,      -- User ID/name
    approved_at TEXT NOT NULL,      -- ISO 8601
    approval_notes TEXT,            -- User comments

    -- Full JSON snapshot
    full_json TEXT NOT NULL,

    FOREIGN KEY (plan_id) REFERENCES governance_plans(id),
    FOREIGN KEY (decision_id) REFERENCES governance_decisions(id)
);

CREATE INDEX IF NOT EXISTS idx_approvals_plan_id ON governance_approvals(plan_id);
CREATE INDEX IF NOT EXISTS idx_approvals_approved_at ON governance_approvals(approved_at DESC);
"""


def init_governance_db(db_path: Optional[Path] = None):
    """
    Initialize governance database schema.

    Args:
        db_path: Path to SQLite database (default: lonelycat_memory.db)
    """
    if db_path is None:
        # Use same DB as memory system
        db_path = Path(__file__).parent.parent.parent / "lonelycat_memory.db"

    conn = sqlite3.connect(str(db_path))
    try:
        # Create tables
        conn.executescript(GOVERNANCE_PLANS_TABLE)
        conn.executescript(GOVERNANCE_CHANGESETS_TABLE)
        conn.executescript(GOVERNANCE_DECISIONS_TABLE)
        conn.executescript(GOVERNANCE_APPROVALS_TABLE)

        conn.commit()

        print(f"[OK] Governance schema initialized: {db_path}")

    finally:
        conn.close()


if __name__ == "__main__":
    # Run this to initialize governance tables
    init_governance_db()
