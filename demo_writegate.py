"""
WriteGate Phase 1 Demo - Complete Governance Workflow

Demonstrates:
1. Create ChangePlan (Agent generates intent)
2. Create ChangeSet (Agent generates diffs)
3. Evaluate with WriteGate (Governance judgment)
4. Approve plan (Human approval if needed)

Philosophy:
- Agent proposes (plan + changeset)
- WriteGate judges (verdict)
- Human decides (approval)
- Phase 2 will execute (Host Executor)
"""

from pathlib import Path
import sys
from datetime import datetime

# Add packages to path (ensure governance can be imported)
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root / "packages"))

from governance import (
    ChangePlan,
    ChangeSet,
    FileChange,
    Operation,
    RiskLevel,
    Verdict,
    WriteGate,
    GovernanceStore,
    GovernanceApproval,
    generate_plan_id,
    generate_changeset_id,
    generate_approval_id
)
from governance.schema import init_governance_db


def demo_low_risk_auto_approve():
    """Demo: LOW risk change with complete gating -> ALLOW."""
    print("\n" + "=" * 60)
    print("Demo 1: LOW Risk Change (Auto-Approve)")
    print("=" * 60)

    # Step 1: Agent creates ChangePlan
    plan = ChangePlan(
        id=generate_plan_id(),
        intent="Update README documentation",
        objective="Add installation instructions",
        rationale="New users need setup guidance",
        affected_paths=["README.md"],
        risk_level_proposed=RiskLevel.LOW,
        rollback_plan="git revert <commit>",
        verification_plan="Read README, verify formatting",
        created_by="agent",
        created_at=datetime.utcnow(),
        confidence=0.95,
        health_checks=["README renders correctly"]
    )

    print(f"\n[1] ChangePlan created: {plan.id}")
    print(f"    Intent: {plan.intent}")
    print(f"    Risk (proposed): {plan.risk_level_proposed.value}")

    # Step 2: Agent generates ChangeSet
    change = FileChange(
        operation=Operation.UPDATE,
        path="README.md",
        old_content="# LonelyCat\n",
        new_content="# LonelyCat\n\n## Installation\n\nRun `make setup`\n",
        diff_unified="@@ -1 +1,4 @@\n # LonelyCat\n+\n+## Installation\n+\n+Run `make setup`\n",
        line_count_delta=3,
        size_bytes=50
    )
    change.compute_hashes()

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id=plan.id,
        changes=[change],
        checksum="",
        generated_by="agent",
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()

    print(f"\n[2] ChangeSet created: {changeset.id}")
    print(f"    Files changed: {len(changeset.changes)}")
    print(f"    Checksum: {changeset.checksum[:16]}...")

    # Step 3: WriteGate evaluates
    writegate = WriteGate()
    decision = writegate.evaluate(plan, changeset)

    print(f"\n[3] WriteGate Evaluation: {decision.id}")
    print(f"    Verdict: {decision.verdict.value}")
    print(f"    Risk (effective): {decision.risk_level_effective.value}")
    if decision.reasons:
        print(f"    Reasons:")
        for reason in decision.reasons:
            print(f"      - {reason}")

    # Step 4: Result
    if decision.is_approved():
        print("\n[OK] Change ALLOWED - no approval needed")
    elif decision.needs_user_approval():
        print("\n[!] Change requires USER APPROVAL")
    else:
        print("\n[X] Change DENIED by policy")


def demo_high_risk_need_approval():
    """Demo: HIGH risk change (critical file) -> NEED_APPROVAL."""
    print("\n" + "=" * 60)
    print("Demo 2: HIGH Risk Change (Needs Approval)")
    print("=" * 60)

    # Plan to modify critical file
    plan = ChangePlan(
        id=generate_plan_id(),
        intent="Fix bug in agent loop",
        objective="Add timeout handling",
        rationale="Current loop may hang indefinitely",
        affected_paths=["apps/core-api/app/main.py"],  # CRITICAL!
        risk_level_proposed=RiskLevel.MEDIUM,
        rollback_plan="git revert <commit> && restart services",
        verification_plan="Run integration tests, check /health",
        created_by="agent",
        created_at=datetime.utcnow(),
        confidence=0.80,
        health_checks=["GET /health returns 200", "Tests pass"]
    )

    change = FileChange(
        operation=Operation.UPDATE,
        path="apps/core-api/app/main.py",
        old_content="def run():\n    while True:\n        process()\n",
        new_content="def run():\n    timeout = 30\n    while True:\n        process(timeout)\n",
        line_count_delta=2,
        size_bytes=100
    )
    change.compute_hashes()

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id=plan.id,
        changes=[change],
        checksum="",
        generated_by="agent",
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()

    print(f"\n[1] ChangePlan: {plan.intent}")
    print(f"    Affected: {plan.affected_paths[0]}")
    print(f"    Risk (proposed): {plan.risk_level_proposed.value}")

    # Evaluate
    writegate = WriteGate()
    decision = writegate.evaluate(plan, changeset)

    print(f"\n[2] WriteGate Evaluation:")
    print(f"    Verdict: {decision.verdict.value}")
    print(f"    Risk (effective): {decision.risk_level_effective.value}")
    print(f"    Escalated: {decision.risk_level_effective > plan.risk_level_proposed}")

    if decision.needs_user_approval():
        print("\n[3] Human Approval Required:")
        print("    User reviews plan + changeset...")
        print("    User approves: YES")

        approval = GovernanceApproval(
            id=generate_approval_id(),
            plan_id=plan.id,
            decision_id=decision.id,
            approved_by="human_user",
            approved_at=datetime.utcnow(),
            approval_notes="Looks good after review"
        )

        print(f"\n[OK] Approval granted: {approval.id}")
        print("    [Phase 1 MVP: Approval recorded, changes NOT executed]")
        print("    [Phase 2 will add Host Executor to apply changes]")


def demo_forbidden_path_deny():
    """Demo: Forbidden path -> DENY."""
    print("\n" + "=" * 60)
    print("Demo 3: Forbidden Path (DENY)")
    print("=" * 60)

    # Attempt to modify forbidden file
    plan = ChangePlan(
        id=generate_plan_id(),
        intent="Update governance policies",
        objective="Add new risk level",
        rationale="Need finer-grained control",
        affected_paths=["agent/policies/default.yaml"],  # FORBIDDEN!
        risk_level_proposed=RiskLevel.MEDIUM,
        rollback_plan="git revert <commit>",
        verification_plan="Restart services",
        created_by="agent",
        created_at=datetime.utcnow(),
        confidence=0.70
    )

    change = FileChange(
        operation=Operation.UPDATE,
        path="agent/policies/default.yaml",
        old_content="risk_levels:\n  low:",
        new_content="risk_levels:\n  very_low:\n  low:",
        line_count_delta=1,
        size_bytes=50
    )

    changeset = ChangeSet(
        id=generate_changeset_id(),
        plan_id=plan.id,
        changes=[change],
        checksum="",
        generated_by="agent",
        generated_at=datetime.utcnow()
    )
    changeset.compute_checksum()

    print(f"\n[1] ChangePlan: {plan.intent}")
    print(f"    Affected: {plan.affected_paths[0]}")
    print(f"    [WARN] This path is FORBIDDEN by policy!")

    # Evaluate
    writegate = WriteGate()
    decision = writegate.evaluate(plan, changeset)

    print(f"\n[2] WriteGate Evaluation:")
    print(f"    Verdict: {decision.verdict.value}")
    print(f"    Risk: {decision.risk_level_effective.value}")
    print(f"    Violated policies: {decision.violated_policies}")
    print(f"    Reasons:")
    for reason in decision.reasons:
        print(f"      - {reason}")

    print("\n[X] Change DENIED - cannot proceed")
    print("    Forbidden paths protect critical governance files")


def main():
    """Run all demos."""
    print("\n" + "=" * 60)
    print("LonelyCat WriteGate - Phase 1 Demo")
    print("=" * 60)
    print("\nPhase 1 MVP Scope:")
    print("  - ChangePlan + ChangeSet generation (Agent)")
    print("  - WriteGate evaluation (Governance engine)")
    print("  - Approval recording (Human decision)")
    print("  - [NOT INCLUDED] Execution (Phase 2 - Host Executor)")

    # Initialize DB
    print("\n[Setup] Initializing governance database...")
    init_governance_db()

    # Run demos
    demo_low_risk_auto_approve()
    demo_high_risk_need_approval()
    demo_forbidden_path_deny()

    print("\n" + "=" * 60)
    print("Demo Complete!")
    print("=" * 60)
    print("\nKey Takeaways:")
    print("  1. WriteGate JUDGES (evaluates) but does NOT EXECUTE")
    print("  2. Risk levels can be ESCALATED by WriteGate")
    print("  3. Forbidden paths are immediately DENIED")
    print("  4. Policy snapshots enable audit replay")
    print("  5. Phase 2 will add Host Executor for safe execution")
    print()


if __name__ == "__main__":
    main()
