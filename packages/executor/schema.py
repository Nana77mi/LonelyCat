"""
Executor Database Schema - Phase 2.2-B / 2.4-A

Provides SQLite tables for execution history and step tracking.

Tables:
- executions: High-level execution records (Phase 2.4-A graph fields via migrations)
- execution_steps: Step-by-step timing and status
- schema_migrations: Migration version tracking (created by migrations)

Why separate from governance DB?
- Governance = decision audit trail (immutable, policy-driven)
- Executor = operational history (performance, errors, retries)
- Different query patterns and retention policies
"""

import sqlite3
from pathlib import Path
from typing import Optional

# SQL Schema
EXECUTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    changeset_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,

    -- Execution metadata
    checksum TEXT NOT NULL,
    verdict TEXT NOT NULL,  -- allow, need_approval, deny
    status TEXT NOT NULL,   -- pending, validating, backing_up, applying, verifying,
                           -- health_checking, completed, failed, rolled_back

    -- Risk and affected paths
    risk_level TEXT,
    affected_paths TEXT,  -- JSON array

    -- Timing
    started_at TEXT NOT NULL,  -- ISO8601
    ended_at TEXT,             -- ISO8601
    duration_seconds REAL,

    -- Results
    files_changed INTEGER DEFAULT 0,
    verification_passed INTEGER DEFAULT 0,  -- 0/1 boolean
    health_checks_passed INTEGER DEFAULT 0, -- 0/1 boolean
    rolled_back INTEGER DEFAULT 0,          -- 0/1 boolean

    -- Paths
    artifact_path TEXT,  -- Path to .lonelycat/executions/{exec_id}

    -- Error tracking
    error_message TEXT,
    error_step TEXT,

    -- Indexing
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status);
CREATE INDEX IF NOT EXISTS idx_executions_started_at ON executions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_executions_plan_id ON executions(plan_id);
CREATE INDEX IF NOT EXISTS idx_executions_verdict ON executions(verdict);
CREATE INDEX IF NOT EXISTS idx_executions_risk_level ON executions(risk_level);
"""

EXECUTION_STEPS_TABLE = """
CREATE TABLE IF NOT EXISTS execution_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,

    -- Step identification
    step_num INTEGER NOT NULL,
    step_name TEXT NOT NULL,  -- validate, backup, apply, verify, health, rollback

    -- Status
    status TEXT NOT NULL,  -- running, completed, failed

    -- Timing
    started_at TEXT NOT NULL,  -- ISO8601
    ended_at TEXT,             -- ISO8601
    duration_seconds REAL,

    -- Error tracking
    error_code TEXT,  -- CHECKSUM_FAILED, VERIFY_FAILED, HEALTH_HTTP_500, PROCESS_DEAD, etc.
    error_message TEXT,

    -- Reference to log file
    log_ref TEXT,  -- steps/01_validate.log

    -- Metadata
    metadata TEXT,  -- JSON for additional context

    FOREIGN KEY (execution_id) REFERENCES executions(execution_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_execution_steps_execution_id ON execution_steps(execution_id);
CREATE INDEX IF NOT EXISTS idx_execution_steps_step_name ON execution_steps(step_name);
CREATE INDEX IF NOT EXISTS idx_execution_steps_status ON execution_steps(status);
"""


def init_executor_db(db_path: Optional[Path] = None):
    """
    Initialize executor database with tables.

    Args:
        db_path: Path to SQLite database file.
                 If None, uses default: .lonelycat/executor.db
    """
    if db_path is None:
        db_path = Path(".lonelycat/executor.db")

    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Create base tables
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(EXECUTIONS_TABLE)
        conn.executescript(EXECUTION_STEPS_TABLE)
        conn.commit()
        print(f"[executor] Database initialized: {db_path}")
    finally:
        conn.close()

    # Run migrations (Phase 2.4-A: execution graph fields, etc.)
    from .migrations import run_migrations
    run_migrations(db_path)


def get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Get database connection.

    Args:
        db_path: Path to SQLite database file

    Returns:
        SQLite connection
    """
    if db_path is None:
        db_path = Path(".lonelycat/executor.db")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row  # Enable column access by name
    return conn


if __name__ == "__main__":
    # Initialize database
    init_executor_db()
    print("Executor database schema created successfully")
