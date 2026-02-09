"""
LonelyCat Governance Storage Layer

Provides persistence for governance artifacts:
- ChangePlan → governance_plans table
- ChangeSet → governance_changesets table
- GovernanceDecision → governance_decisions table
- GovernanceApproval → governance_approvals table

Philosophy:
- Append-only (no updates to records)
- Full JSON snapshots for audit replay
- Type-safe conversion between models and DB rows
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from .models import (
    ChangePlan,
    ChangeSet,
    GovernanceDecision,
    GovernanceApproval,
    Verdict
)


class GovernanceStore:
    """Storage layer for governance artifacts."""

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize storage.

        Args:
            db_path: Path to SQLite database (default: lonelycat_memory.db)
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "lonelycat_memory.db"

        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        """Create database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ==================== ChangePlan Operations ====================

    def save_plan(self, plan: ChangePlan):
        """Save ChangePlan to database."""
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO governance_plans (
                    id, intent, objective, rationale,
                    affected_paths, dependencies,
                    risk_level_proposed, risk_level_effective, risk_escalation_reason,
                    rollback_plan, verification_plan, health_checks,
                    policy_refs,
                    created_by, created_at, confidence, run_id,
                    full_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                plan.id,
                plan.intent,
                plan.objective,
                plan.rationale,
                json.dumps(plan.affected_paths),
                json.dumps(plan.dependencies),
                plan.risk_level_proposed.value,
                plan.risk_level_effective.value if plan.risk_level_effective else None,
                plan.risk_escalation_reason,
                plan.rollback_plan,
                plan.verification_plan,
                json.dumps(plan.health_checks),
                json.dumps(plan.policy_refs),
                plan.created_by,
                plan.created_at.isoformat(),
                plan.confidence,
                plan.run_id,
                json.dumps(plan.to_dict())
            ))
            conn.commit()
        finally:
            conn.close()

    def get_plan(self, plan_id: str) -> Optional[ChangePlan]:
        """Retrieve ChangePlan by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT full_json FROM governance_plans WHERE id = ?",
                (plan_id,)
            ).fetchone()

            if row:
                return ChangePlan.from_dict(json.loads(row["full_json"]))
            return None
        finally:
            conn.close()

    def list_plans(
        self,
        created_by: Optional[str] = None,
        risk_level: Optional[str] = None,
        limit: int = 50
    ) -> List[ChangePlan]:
        """List ChangePlans with optional filters."""
        conn = self._connect()
        try:
            query = "SELECT full_json FROM governance_plans WHERE 1=1"
            params = []

            if created_by:
                query += " AND created_by = ?"
                params.append(created_by)

            if risk_level:
                query += " AND risk_level_effective = ?"
                params.append(risk_level)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [ChangePlan.from_dict(json.loads(row["full_json"])) for row in rows]
        finally:
            conn.close()

    # ==================== ChangeSet Operations ====================

    def save_changeset(self, changeset: ChangeSet):
        """Save ChangeSet to database."""
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO governance_changesets (
                    id, plan_id, changes, checksum,
                    generated_by, generated_at,
                    full_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                changeset.id,
                changeset.plan_id,
                json.dumps([c.to_dict() for c in changeset.changes]),
                changeset.checksum,
                changeset.generated_by,
                changeset.generated_at.isoformat(),
                json.dumps(changeset.to_dict())
            ))
            conn.commit()
        finally:
            conn.close()

    def get_changeset(self, changeset_id: str) -> Optional[ChangeSet]:
        """Retrieve ChangeSet by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT full_json FROM governance_changesets WHERE id = ?",
                (changeset_id,)
            ).fetchone()

            if row:
                return ChangeSet.from_dict(json.loads(row["full_json"]))
            return None
        finally:
            conn.close()

    def get_changeset_for_plan(self, plan_id: str) -> Optional[ChangeSet]:
        """Retrieve ChangeSet for a given plan_id."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT full_json FROM governance_changesets WHERE plan_id = ? ORDER BY generated_at DESC LIMIT 1",
                (plan_id,)
            ).fetchone()

            if row:
                return ChangeSet.from_dict(json.loads(row["full_json"]))
            return None
        finally:
            conn.close()

    # ==================== GovernanceDecision Operations ====================

    def save_decision(self, decision: GovernanceDecision):
        """Save GovernanceDecision to database."""
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO governance_decisions (
                    id, plan_id, changeset_id,
                    verdict, reasons, violated_policies, required_actions,
                    risk_level_effective,
                    policy_snapshot_hash, agent_source_hash, projection_hash, writegate_version,
                    evaluated_at, evaluator,
                    full_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                decision.id,
                decision.plan_id,
                decision.changeset_id,
                decision.verdict.value,
                json.dumps(decision.reasons),
                json.dumps(decision.violated_policies),
                json.dumps(decision.required_actions),
                decision.risk_level_effective.value,
                decision.policy_snapshot_hash,
                decision.agent_source_hash,
                decision.projection_hash,
                decision.writegate_version,
                decision.evaluated_at.isoformat(),
                decision.evaluator,
                json.dumps(decision.to_dict())
            ))
            conn.commit()
        finally:
            conn.close()

    def get_decision(self, decision_id: str) -> Optional[GovernanceDecision]:
        """Retrieve GovernanceDecision by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT full_json FROM governance_decisions WHERE id = ?",
                (decision_id,)
            ).fetchone()

            if row:
                return GovernanceDecision.from_dict(json.loads(row["full_json"]))
            return None
        finally:
            conn.close()

    def get_decision_for_plan(self, plan_id: str) -> Optional[GovernanceDecision]:
        """Retrieve latest GovernanceDecision for a plan."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT full_json FROM governance_decisions WHERE plan_id = ? ORDER BY evaluated_at DESC LIMIT 1",
                (plan_id,)
            ).fetchone()

            if row:
                return GovernanceDecision.from_dict(json.loads(row["full_json"]))
            return None
        finally:
            conn.close()

    def list_decisions(
        self,
        verdict: Optional[Verdict] = None,
        limit: int = 50
    ) -> List[GovernanceDecision]:
        """List GovernanceDecisions with optional filters."""
        conn = self._connect()
        try:
            query = "SELECT full_json FROM governance_decisions WHERE 1=1"
            params = []

            if verdict:
                query += " AND verdict = ?"
                params.append(verdict.value)

            query += " ORDER BY evaluated_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [GovernanceDecision.from_dict(json.loads(row["full_json"])) for row in rows]
        finally:
            conn.close()

    # ==================== GovernanceApproval Operations ====================

    def save_approval(self, approval: GovernanceApproval):
        """Save GovernanceApproval to database."""
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO governance_approvals (
                    id, plan_id, decision_id,
                    approved_by, approved_at, approval_notes,
                    full_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                approval.id,
                approval.plan_id,
                approval.decision_id,
                approval.approved_by,
                approval.approved_at.isoformat(),
                approval.approval_notes,
                json.dumps(approval.to_dict())
            ))
            conn.commit()
        finally:
            conn.close()

    def get_approval_for_plan(self, plan_id: str) -> Optional[GovernanceApproval]:
        """Retrieve approval for a plan."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT full_json FROM governance_approvals WHERE plan_id = ? ORDER BY approved_at DESC LIMIT 1",
                (plan_id,)
            ).fetchone()

            if row:
                return GovernanceApproval.from_dict(json.loads(row["full_json"]))
            return None
        finally:
            conn.close()

    # ==================== Query Helpers ====================

    def plan_has_approval(self, plan_id: str) -> bool:
        """Check if a plan has been approved."""
        return self.get_approval_for_plan(plan_id) is not None

    def get_full_governance_record(self, plan_id: str) -> dict:
        """
        Get complete governance record for a plan.

        Returns:
            dict with plan, changeset, decision, approval (if exists)
        """
        return {
            "plan": self.get_plan(plan_id),
            "changeset": self.get_changeset_for_plan(plan_id),
            "decision": self.get_decision_for_plan(plan_id),
            "approval": self.get_approval_for_plan(plan_id)
        }
