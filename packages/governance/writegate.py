"""
LonelyCat WriteGate - Governance Enforcement Engine

Philosophy: WriteGate is the JUDGE, not the EXECUTOR.
- Evaluates ChangePlan + ChangeSet against policies
- Returns Verdict: ALLOW / NEED_APPROVAL / DENY
- Stores audit metadata (policy snapshots)
- NEVER executes changes (Phase 2 Host Executor does that)

Key Principles:
- Risk escalation: may upgrade risk_level_proposed -> risk_level_effective
- Policy enforcement: forbidden paths = immediate DENY
- Gating checks: missing rollback/verify -> NEED_APPROVAL
- Audit trail: policy_snapshot_hash for replay
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import hashlib
import yaml
import fnmatch

from .models import (
    ChangePlan,
    ChangeSet,
    GovernanceDecision,
    Verdict,
    RiskLevel,
    Operation,
    generate_decision_id
)


class WriteGate:
    """
    Governance Enforcement Engine - evaluates change requests.

    Flow:
        1. Load policies from agent/policies/default.yaml
        2. evaluate(plan, changeset) -> decision
        3. Return Verdict with reasons
    """

    VERSION = "1.0.0"

    def __init__(self, policies_path: Optional[Path] = None):
        """
        Initialize WriteGate with policies.

        Args:
            policies_path: Path to policies YAML (default: agent/policies/default.yaml)
        """
        if policies_path is None:
            # Default to repo root/agent/policies/default.yaml
            repo_root = Path(__file__).parent.parent.parent
            policies_path = repo_root / "agent" / "policies" / "default.yaml"

        self.policies_path = policies_path
        self.policies = self._load_policies()
        self.policy_snapshot_hash = self._compute_policy_hash()

    def _load_policies(self) -> dict:
        """Load policies from YAML file."""
        if not self.policies_path.exists():
            raise FileNotFoundError(f"Policies not found: {self.policies_path}")

        content = self.policies_path.read_text(encoding="utf-8")

        # Handle multiple YAML documents (policies use --- separators)
        documents = []
        for doc in yaml.safe_load_all(content):
            if doc:
                documents.append(doc)

        # Merge all documents
        merged = {}
        for doc in documents:
            if isinstance(doc, dict):
                merged.update(doc)

        return merged

    def _compute_policy_hash(self) -> str:
        """Compute SHA256 hash of policies file."""
        content = self.policies_path.read_text(encoding="utf-8")
        return hashlib.sha256(content.encode()).hexdigest()

    def evaluate(
        self,
        plan: ChangePlan,
        changeset: ChangeSet,
        agent_source_hash: Optional[str] = None,
        projection_hash: Optional[str] = None
    ) -> GovernanceDecision:
        """
        Evaluate ChangePlan + ChangeSet against policies.

        This is the core WriteGate function - it judges but does NOT execute.

        Args:
            plan: ChangePlan describing intent
            changeset: ChangeSet with actual diffs
            agent_source_hash: Hash of agent/ directory (optional)
            projection_hash: Hash of AGENTS.md/CLAUDE.md (optional)

        Returns:
            GovernanceDecision with verdict and reasons
        """
        reasons = []
        violated_policies = []
        required_actions = []

        # Check 1: Forbidden Paths (immediate DENY)
        forbidden_check = self._check_forbidden_paths(changeset)
        if forbidden_check["verdict"] == Verdict.DENY:
            return self._create_decision(
                plan=plan,
                changeset=changeset,
                verdict=Verdict.DENY,
                reasons=forbidden_check["reasons"],
                violated_policies=forbidden_check["violated_policies"],
                required_actions=["Remove forbidden path modifications"],
                risk_level_effective=RiskLevel.CRITICAL,
                agent_source_hash=agent_source_hash,
                projection_hash=projection_hash
            )

        # Check 2: Risk Escalation (compute effective risk)
        risk_check = self._check_risk_escalation(plan, changeset)
        risk_level_effective = risk_check["risk_level_effective"]
        if risk_check["escalated"]:
            reasons.append(risk_check["reason"])

        # Check 3: Rollback/Verify Gating
        gating_check = self._check_gating_requirements(plan)
        if not gating_check["passed"]:
            reasons.extend(gating_check["reasons"])
            required_actions.extend(gating_check["required_actions"])

        # Check 4: WriteGate Trigger Rules
        trigger_check = self._check_writegate_triggers(plan, changeset)
        if trigger_check["requires_approval"]:
            reasons.extend(trigger_check["reasons"])

        # Determine final verdict
        verdict = self._determine_verdict(
            risk_level_effective=risk_level_effective,
            gating_passed=gating_check["passed"],
            requires_approval=trigger_check["requires_approval"]
        )

        return self._create_decision(
            plan=plan,
            changeset=changeset,
            verdict=verdict,
            reasons=reasons,
            violated_policies=violated_policies,
            required_actions=required_actions,
            risk_level_effective=risk_level_effective,
            agent_source_hash=agent_source_hash,
            projection_hash=projection_hash
        )

    def _check_forbidden_paths(self, changeset: ChangeSet) -> dict:
        """
        Check if any changes touch forbidden paths.

        Returns:
            dict with verdict, reasons, violated_policies
        """
        forbidden_paths = self.policies.get("forbidden_paths", [])

        for change in changeset.changes:
            for forbidden_pattern in forbidden_paths:
                if self._path_matches(change.path, forbidden_pattern):
                    return {
                        "verdict": Verdict.DENY,
                        "reasons": [f"Path '{change.path}' matches forbidden pattern '{forbidden_pattern}'"],
                        "violated_policies": ["forbidden_paths"]
                    }

        return {
            "verdict": Verdict.ALLOW,
            "reasons": [],
            "violated_policies": []
        }

    def _check_risk_escalation(self, plan: ChangePlan, changeset: ChangeSet) -> dict:
        """
        Compute risk_level_effective (may escalate from proposed).

        Escalation triggers:
        - Critical file patterns (*.py in packages/, apps/)
        - Large changes (>500 lines)
        - DELETE operations
        - Database schema changes

        Returns:
            dict with risk_level_effective, escalated (bool), reason
        """
        risk_level = plan.risk_level_proposed
        escalation_reasons = []

        # Check 1: Critical file patterns
        critical_patterns = [
            "packages/**/*.py",
            "apps/**/*.py",
            "**/migrations/*.py",
            "agent/policies/default.yaml"
        ]

        for change in changeset.changes:
            for pattern in critical_patterns:
                if self._path_matches(change.path, pattern):
                    if risk_level < RiskLevel.MEDIUM:
                        risk_level = RiskLevel.MEDIUM
                        escalation_reasons.append(
                            f"Critical file pattern '{pattern}' matched by '{change.path}'"
                        )

        # Check 2: Large changes
        total_lines = changeset.total_lines_changed()
        if total_lines > 500:
            if risk_level < RiskLevel.HIGH:
                risk_level = RiskLevel.HIGH
                escalation_reasons.append(f"Large change ({total_lines} lines)")

        # Check 3: DELETE operations
        delete_count = sum(1 for c in changeset.changes if c.operation == Operation.DELETE)
        if delete_count > 0:
            if risk_level < RiskLevel.MEDIUM:
                risk_level = RiskLevel.MEDIUM
                escalation_reasons.append(f"{delete_count} file deletion(s)")

        # Check 4: Database schema
        db_patterns = ["**/migrations/*.py", "**/schema.sql", "**/alembic/**"]
        for change in changeset.changes:
            for pattern in db_patterns:
                if self._path_matches(change.path, pattern):
                    if risk_level < RiskLevel.HIGH:
                        risk_level = RiskLevel.HIGH
                        escalation_reasons.append("Database schema modification")

        escalated = risk_level > plan.risk_level_proposed
        reason = "; ".join(escalation_reasons) if escalated else ""

        return {
            "risk_level_effective": risk_level,
            "escalated": escalated,
            "reason": f"Risk escalated to {risk_level.value}: {reason}" if escalated else ""
        }

    def _check_gating_requirements(self, plan: ChangePlan) -> dict:
        """
        Check if rollback/verification plans exist.

        Returns:
            dict with passed (bool), reasons, required_actions
        """
        reasons = []
        required_actions = []

        # Check rollback plan
        if not plan.rollback_plan or plan.rollback_plan.strip() == "":
            reasons.append("Missing rollback plan")
            required_actions.append("Add rollback plan")

        # Check verification plan
        if not plan.verification_plan or plan.verification_plan.strip() == "":
            reasons.append("Missing verification plan")
            required_actions.append("Add verification plan")

        # Check health checks (recommended for MEDIUM+ risk)
        if plan.risk_level_proposed >= RiskLevel.MEDIUM:
            if not plan.health_checks or len(plan.health_checks) == 0:
                reasons.append("No health checks defined for MEDIUM+ risk change")
                required_actions.append("Add health checks")

        passed = len(reasons) == 0

        return {
            "passed": passed,
            "reasons": reasons,
            "required_actions": required_actions
        }

    def _check_writegate_triggers(self, plan: ChangePlan, changeset: ChangeSet) -> dict:
        """
        Check if WriteGate rules require approval.

        From policies: writegate_rules -> triggers

        Returns:
            dict with requires_approval (bool), reasons
        """
        writegate_rules = self.policies.get("writegate_rules", {})
        triggers = writegate_rules.get("triggers", [])

        reasons = []

        for trigger in triggers:
            path_patterns = trigger.get("path_matches", [])
            if isinstance(path_patterns, str):
                path_patterns = [path_patterns]

            for change in changeset.changes:
                for pattern in path_patterns:
                    if self._path_matches(change.path, pattern):
                        reasons.append(
                            f"WriteGate trigger: path '{change.path}' matches '{pattern}'"
                        )

        requires_approval = len(reasons) > 0

        return {
            "requires_approval": requires_approval,
            "reasons": reasons
        }

    def _determine_verdict(
        self,
        risk_level_effective: RiskLevel,
        gating_passed: bool,
        requires_approval: bool
    ) -> Verdict:
        """
        Determine final verdict based on checks.

        Logic:
        - If gating not passed (missing rollback/verify): NEED_APPROVAL
        - If risk >= HIGH: NEED_APPROVAL
        - If WriteGate triggered: NEED_APPROVAL
        - Otherwise: ALLOW
        """
        if not gating_passed:
            return Verdict.NEED_APPROVAL

        if risk_level_effective >= RiskLevel.HIGH:
            return Verdict.NEED_APPROVAL

        if requires_approval:
            return Verdict.NEED_APPROVAL

        # LOW/MEDIUM risk with complete gating
        return Verdict.ALLOW

    def _create_decision(
        self,
        plan: ChangePlan,
        changeset: ChangeSet,
        verdict: Verdict,
        reasons: List[str],
        violated_policies: List[str],
        required_actions: List[str],
        risk_level_effective: RiskLevel,
        agent_source_hash: Optional[str],
        projection_hash: Optional[str]
    ) -> GovernanceDecision:
        """Create GovernanceDecision with full audit metadata."""
        return GovernanceDecision(
            id=generate_decision_id(),
            plan_id=plan.id,
            changeset_id=changeset.id,
            verdict=verdict,
            reasons=reasons,
            violated_policies=violated_policies,
            required_actions=required_actions,
            risk_level_effective=risk_level_effective,
            policy_snapshot_hash=self.policy_snapshot_hash,
            agent_source_hash=agent_source_hash or "unknown",
            projection_hash=projection_hash,
            writegate_version=self.VERSION,
            evaluated_at=datetime.utcnow(),
            evaluator="writegate_engine"
        )

    def _path_matches(self, path: str, pattern: str) -> bool:
        """
        Check if path matches glob pattern.

        Supports:
        - **/*.py (recursive)
        - *.txt (single level)
        - apps/*/config.yaml (wildcards)
        """
        # Normalize path separators
        path = path.replace("\\", "/")
        pattern = pattern.replace("\\", "/")

        # Use fnmatch for glob matching
        # Note: fnmatch doesn't support ** natively, so we handle it
        if "**" in pattern:
            # Convert ** to recursive match
            # Example: "apps/**/*.py" -> any .py file under apps/
            parts = pattern.split("**")
            if len(parts) == 2:
                prefix = parts[0].rstrip("/")
                suffix = parts[1].lstrip("/")

                # Check if path starts with prefix and ends with suffix pattern
                if prefix and not path.startswith(prefix):
                    return False

                if suffix:
                    return fnmatch.fnmatch(path, f"*{suffix}")

                return True

        return fnmatch.fnmatch(path, pattern)


def compute_agent_source_hash(agent_dir: Path) -> str:
    """
    Compute hash of agent/ directory contents.

    Used for audit trail - changes to agent/ may affect governance decisions.
    """
    file_hashes = []

    for file_path in sorted(agent_dir.rglob("*")):
        if file_path.is_file():
            content = file_path.read_bytes()
            file_hash = hashlib.sha256(content).hexdigest()
            file_hashes.append(f"{file_path.relative_to(agent_dir)}:{file_hash}")

    combined = "\n".join(file_hashes)
    return hashlib.sha256(combined.encode()).hexdigest()


def compute_projection_hash(projections: List[Path]) -> str:
    """
    Compute hash of projection files (AGENTS.md, CLAUDE.md).

    Used for audit trail - projections reflect agent/ state.
    """
    file_hashes = []

    for proj_path in sorted(projections):
        if proj_path.exists():
            content = proj_path.read_bytes()
            file_hash = hashlib.sha256(content).hexdigest()
            file_hashes.append(f"{proj_path.name}:{file_hash}")

    combined = "\n".join(file_hashes)
    return hashlib.sha256(combined.encode()).hexdigest()
