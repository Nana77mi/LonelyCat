"""
Executor Database Migrations - Phase 2.4-A

Provides versioned schema migrations for executor database.

Philosophy:
- Append-only: Never delete columns, only add
- Backward compatible: Old code can still work with new schema
- Testable: Each migration has rollback capability (for testing)
"""

import sqlite3
from pathlib import Path
from typing import List, Callable, Optional
from dataclasses import dataclass


@dataclass
class Migration:
    """Database migration."""
    version: int
    description: str
    up: Callable[[sqlite3.Connection], None]
    down: Callable[[sqlite3.Connection], None]  # For testing rollback


# ==================== Migration 001: Execution Graph (Phase 2.4-A) ====================

def migration_001_up(conn: sqlite3.Connection):
    """
    Add execution graph fields (Phase 2.4-A).

    New fields:
    - correlation_id: Links related executions (same task chain/agent loop)
    - parent_execution_id: Points to triggering execution (retry/repair/child)
    - trigger_kind: How this execution was triggered
    - run_id: Optional link to run system
    """
    cursor = conn.cursor()

    # Check if migration already applied
    cursor.execute("PRAGMA table_info(executions)")
    columns = [row[1] for row in cursor.fetchall()]

    if "correlation_id" not in columns:
        # Add new columns
        cursor.execute("""
            ALTER TABLE executions
            ADD COLUMN correlation_id TEXT
        """)

        cursor.execute("""
            ALTER TABLE executions
            ADD COLUMN parent_execution_id TEXT
        """)

        cursor.execute("""
            ALTER TABLE executions
            ADD COLUMN trigger_kind TEXT DEFAULT 'manual'
        """)

        cursor.execute("""
            ALTER TABLE executions
            ADD COLUMN run_id TEXT
        """)

        # Create indexes for new fields
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_executions_correlation_id
            ON executions(correlation_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_executions_parent_execution_id
            ON executions(parent_execution_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_executions_trigger_kind
            ON executions(trigger_kind)
        """)

        print("[migration] 001: Added execution graph fields")
    else:
        print("[migration] 001: Already applied, skipping")


def migration_001_down(conn: sqlite3.Connection):
    """
    Rollback migration 001 (for testing only).

    Note: SQLite doesn't support DROP COLUMN directly.
    This is a destructive operation - recreate table without new columns.
    """
    cursor = conn.cursor()

    # Create new table without graph fields
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS executions_old AS
        SELECT
            execution_id, plan_id, changeset_id, decision_id,
            checksum, verdict, status,
            risk_level, affected_paths,
            started_at, ended_at, duration_seconds,
            files_changed, verification_passed, health_checks_passed, rolled_back,
            artifact_path, error_message, error_step, created_at
        FROM executions
    """)

    cursor.execute("DROP TABLE executions")
    cursor.execute("ALTER TABLE executions_old RENAME TO executions")

    # Recreate indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_executions_started_at ON executions(started_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_executions_plan_id ON executions(plan_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_executions_verdict ON executions(verdict)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_executions_risk_level ON executions(risk_level)")

    print("[migration] 001: Rolled back (testing only)")


# ==================== Migration 002: Repair in Graph (Phase 2.5-D) ====================

def migration_002_up(conn: sqlite3.Connection):
    """Add is_repair and repair_for_execution_id to executions."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(executions)")
    columns = [row[1] for row in cursor.fetchall()]

    if "is_repair" not in columns:
        cursor.execute("""
            ALTER TABLE executions
            ADD COLUMN is_repair INTEGER DEFAULT 0
        """)
        cursor.execute("""
            ALTER TABLE executions
            ADD COLUMN repair_for_execution_id TEXT
        """)
        print("[migration] 002: Added is_repair, repair_for_execution_id")
    else:
        print("[migration] 002: Already applied, skipping")


def migration_002_down(conn: sqlite3.Connection):
    """Rollback 002 (testing only): SQLite cannot DROP COLUMN; no-op or recreate table."""
    print("[migration] 002: Rollback not implemented (SQLite limitation)")


# ==================== Migration 003: execution_paths (Phase 2.5-B) ====================

def migration_003_up(conn: sqlite3.Connection):
    """Create execution_paths table and backfill from executions.affected_paths."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS execution_paths (
            execution_id TEXT NOT NULL,
            path TEXT NOT NULL,
            PRIMARY KEY (execution_id, path)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_execution_paths_execution_id
        ON execution_paths(execution_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_execution_paths_path
        ON execution_paths(path)
    """)
    # Backfill from executions.affected_paths (JSON array)
    cursor.execute("SELECT execution_id, affected_paths FROM executions WHERE affected_paths IS NOT NULL AND affected_paths != '[]'")
    rows = cursor.fetchall()
    inserted = 0
    skipped = 0
    for row in rows:
        exec_id = row[0]
        raw = row[1]
        try:
            paths = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(paths, list):
                skipped += 1
                continue
            for p in paths:
                if isinstance(p, str) and p.strip():
                    cursor.execute(
                        "INSERT OR IGNORE INTO execution_paths (execution_id, path) VALUES (?, ?)",
                        (exec_id, p.strip())
                    )
                    inserted += cursor.rowcount
        except Exception:
            skipped += 1
    print(f"[migration] 003: execution_paths created and backfilled (inserted={inserted}, skipped_rows={skipped})")


def migration_003_down(conn: sqlite3.Connection):
    """Drop execution_paths table."""
    conn.execute("DROP TABLE IF EXISTS execution_paths")
    print("[migration] 003: execution_paths dropped")


# ==================== Migration Registry ====================

MIGRATIONS: List[Migration] = [
    Migration(
        version=1,
        description="Add execution graph fields (correlation_id, parent_execution_id, trigger_kind, run_id)",
        up=migration_001_up,
        down=migration_001_down
    ),
    Migration(
        version=2,
        description="Add is_repair, repair_for_execution_id (Phase 2.5-D)",
        up=migration_002_up,
        down=migration_002_down
    ),
    Migration(
        version=3,
        description="execution_paths table + backfill (Phase 2.5-B)",
        up=migration_003_up,
        down=migration_003_down
    ),
]


# ==================== Migration Engine ====================

def get_current_version(conn: sqlite3.Connection) -> int:
    """
    Get current schema version.

    Returns:
        Current version number (0 if migrations table doesn't exist)
    """
    cursor = conn.cursor()

    # Check if migrations table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='schema_migrations'
    """)

    if not cursor.fetchone():
        return 0

    # Get latest version
    cursor.execute("SELECT MAX(version) FROM schema_migrations")
    result = cursor.fetchone()
    return result[0] if result[0] is not None else 0


def record_migration(conn: sqlite3.Connection, version: int, description: str):
    """Record migration in schema_migrations table."""
    cursor = conn.cursor()

    # Create migrations table if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Record migration
    cursor.execute("""
        INSERT OR REPLACE INTO schema_migrations (version, description)
        VALUES (?, ?)
    """, (version, description))


def run_migrations(db_path: Optional[Path] = None, target_version: Optional[int] = None):
    """
    Run pending migrations.

    Args:
        db_path: Path to database file
        target_version: Target version to migrate to (None = latest)

    Returns:
        Number of migrations applied
    """
    if db_path is None:
        db_path = Path(".lonelycat/executor.db")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        current_version = get_current_version(conn)
        target = target_version if target_version is not None else max(m.version for m in MIGRATIONS)

        applied_count = 0

        for migration in MIGRATIONS:
            if migration.version <= current_version:
                continue

            if migration.version > target:
                break

            print(f"[migration] Applying {migration.version}: {migration.description}")

            # Run migration
            migration.up(conn)

            # Record migration
            record_migration(conn, migration.version, migration.description)

            applied_count += 1

        conn.commit()

        if applied_count > 0:
            print(f"[migration] Applied {applied_count} migration(s), now at version {target}")
        else:
            print(f"[migration] No pending migrations (current version: {current_version})")

        return applied_count

    except Exception as e:
        conn.rollback()
        print(f"[migration] Error: {e}")
        raise
    finally:
        conn.close()


def rollback_migration(db_path: Optional[Path] = None, target_version: int = 0):
    """
    Rollback migrations (for testing only).

    WARNING: This is destructive! Only use for testing.

    Args:
        db_path: Path to database file
        target_version: Version to roll back to
    """
    if db_path is None:
        db_path = Path(".lonelycat/executor.db")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        current_version = get_current_version(conn)

        # Rollback in reverse order
        for migration in reversed(MIGRATIONS):
            if migration.version <= target_version:
                break

            if migration.version > current_version:
                continue

            print(f"[migration] Rolling back {migration.version}: {migration.description}")

            # Run rollback
            migration.down(conn)

            # Remove migration record
            cursor = conn.cursor()
            cursor.execute("DELETE FROM schema_migrations WHERE version = ?", (migration.version,))

        conn.commit()
        print(f"[migration] Rolled back to version {target_version}")

    except Exception as e:
        conn.rollback()
        print(f"[migration] Rollback error: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Executor database migrations")
    parser.add_argument("--db", type=Path, help="Database path")
    parser.add_argument("--rollback", type=int, metavar="VERSION", help="Rollback to version (TESTING ONLY)")

    args = parser.parse_args()

    if args.rollback is not None:
        print(f"WARNING: Rolling back to version {args.rollback} (testing only)")
        rollback_migration(args.db, args.rollback)
    else:
        run_migrations(args.db)
