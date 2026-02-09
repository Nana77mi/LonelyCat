"""
Phase 2 - Host Executor Demo

Demonstrates complete flow:
    Planner → ChangePlan + ChangeSet
        ↓
    WriteGate → Evaluation (ALLOW)
        ↓
    Executor → Apply changes (safely)
        ↓
    Verification → Run tests
        ↓
    Health Checks → Validate system

This is the FULL STACK working together!
"""

from pathlib import Path
import sys
import tempfile

# Add packages to path
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root / "packages"))

from planner import PlannerOrchestrator
from governance import WriteGate, GovernanceStore
from executor import HostExecutor


def demo_full_stack():
    """Demonstrate complete Planner → WriteGate → Executor flow."""
    print("\n" + "=" * 70)
    print("Phase 2 - Host Executor Demo")
    print("FULL STACK: Planner → WriteGate → Executor")
    print("=" * 70)

    # Create temp workspace for demo
    temp_workspace = Path(tempfile.mkdtemp(prefix="lonelycat_demo_"))
    print(f"\nDemo workspace: {temp_workspace}")

    # Initialize components
    planner = PlannerOrchestrator()
    writegate = WriteGate()
    executor = HostExecutor(temp_workspace)

    # ========== Step 1: Planner generates ChangePlan ==========
    print("\n" + "-" * 70)
    print("Step 1: Planner Layer - Generate ChangePlan")
    print("-" * 70)

    user_intent = "Create README.md file with project description"

    planner_result = planner.create_plan_from_intent(
        user_intent=user_intent,
        created_by="demo"
    )

    plan = planner_result["plan"]
    changeset = planner_result["changeset"]
    context = planner_result["context"]

    print(f"[Planner] Created ChangePlan: {plan.id}")
    print(f"  Intent: {plan.intent}")
    print(f"  Risk: {plan.risk_level_proposed.value}")
    print(f"  Rollback: {plan.rollback_plan[:50]}...")
    print(f"  Verification: {plan.verification_plan[:50]}...")
    print(f"  State: {context.current_state.value}")

    # Fix changeset to have real content
    from governance import FileChange, Operation
    from datetime import datetime

    real_change = FileChange(
        operation=Operation.CREATE,
        path="README.md",
        new_content="""# LonelyCat

Self-Evolving Local AgentOS

## Architecture

Planner → WriteGate → Executor

## Status

Phase 2 Complete!
"""
    )
    real_change.compute_hashes()

    changeset.changes = [real_change]
    changeset.compute_checksum()

    print(f"[Planner] Created ChangeSet: {changeset.id}")
    print(f"  Files: {len(changeset.changes)}")
    print(f"  Checksum: {changeset.checksum[:16]}...")

    # ========== Step 2: WriteGate evaluates ==========
    print("\n" + "-" * 70)
    print("Step 2: WriteGate - Governance Evaluation")
    print("-" * 70)

    decision = writegate.evaluate(plan, changeset)

    print(f"[WriteGate] Decision: {decision.id}")
    print(f"  Verdict: {decision.verdict.value}")
    print(f"  Risk (effective): {decision.risk_level_effective.value}")
    if decision.reasons:
        print(f"  Reasons:")
        for reason in decision.reasons:
            print(f"    - {reason}")

    # ========== Step 3: Executor applies changes ==========
    if decision.is_approved():
        print("\n" + "-" * 70)
        print("Step 3: Host Executor - Apply Changes")
        print("-" * 70)

        result = executor.execute(plan, changeset, decision)

        print(f"[Executor] Execution: {result.context.id}")
        print(f"  Success: {result.success}")
        print(f"  Status: {result.context.status.value}")
        print(f"  Files changed: {result.files_changed}")
        print(f"  Duration: {result.duration_seconds:.2f}s")

        if result.success:
            print(f"\n[Verification] Passed: {result.verification_passed}")
            print(f"[Health Checks] Passed: {result.health_checks_passed}")

            # Show created file
            readme_path = temp_workspace / "README.md"
            if readme_path.exists():
                print(f"\n[Result] Created file: {readme_path}")
                print("--- Content ---")
                print(readme_path.read_text())
                print("--- End ---")
        else:
            print(f"\n[ERROR] {result.message}")
            if result.context.rolled_back:
                print("[Rollback] Changes were rolled back")

    else:
        print(f"\n[BLOCKED] Cannot execute: {decision.verdict.value}")
        print(f"Reasons: {', '.join(decision.reasons)}")

    # ========== Summary ==========
    print("\n" + "=" * 70)
    print("Demo Complete!")
    print("=" * 70)
    print("\nKey Takeaways:")
    print("1. Planner generates complete ChangePlan (with auto safety fields)")
    print("2. WriteGate validates against policies (governance)")
    print("3. Executor applies changes ONLY if approved (safe execution)")
    print("4. Verification runs automatically (quality gate)")
    print("5. Rollback happens automatically on failure (safety net)")
    print("\nFull Stack Architecture:")
    print("  Cognition Layer (agent/) → AI self-awareness")
    print("  Planner Layer → Decision orchestration")
    print("  Governance Layer (WriteGate) → Policy enforcement")
    print("  Executor Layer → Safe execution ← Phase 2!")
    print()

    # Cleanup
    import shutil
    shutil.rmtree(temp_workspace)


if __name__ == "__main__":
    demo_full_stack()
