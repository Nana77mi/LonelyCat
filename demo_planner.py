"""
Phase 1.5 Planner Layer Demo

Demonstrates:
- Intent decomposition (deterministic)
- Risk shaping (auto-generated safety fields)
- State machine orchestration
- Planner → WriteGate integration readiness
"""

from pathlib import Path
import sys

# Add packages to path
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root / "packages"))

from planner import (
    PlannerOrchestrator,
    IntentDecomposer,
    PlannerState
)


def demo_planner_layer():
    """Demonstrate Planner Layer capabilities."""
    print("\n" + "=" * 70)
    print("Phase 1.5 - Planner Layer Demo")
    print("=" * 70)
    print("\nKey Insight: Planner shapes thinking, LLM provides reasoning")
    print("             (NOT: LLM decides everything)")

    orchestrator = PlannerOrchestrator()
    decomposer = IntentDecomposer()

    # Test cases
    test_intents = [
        "Fix memory conflict resolution bug",
        "Add new web search provider",
        "Update WriteGate documentation",
        "Optimize database query performance"
    ]

    for i, intent in enumerate(test_intents, 1):
        print(f"\n{'-' * 70}")
        print(f"Test {i}: {intent}")
        print("-" * 70)

        # Step 1: Decompose intent (deterministic)
        decomposed = decomposer.decompose(intent)

        print(f"\n[Decomposition]")
        print(f"  Type: {decomposed.intent_type.value}")
        print(f"  Needs Analysis: {decomposed.needs_analysis}")
        print(f"  Estimated Risk: {decomposed.estimated_risk}")
        print(f"  Approach: {decomposed.suggested_approach}")
        if decomposed.affected_components:
            print(f"  Components: {', '.join(decomposed.affected_components)}")

        # Step 2: Generate plan (with auto risk shaping)
        result = orchestrator.create_plan_from_intent(intent, created_by="demo")

        plan = result["plan"]
        context = result["context"]

        print(f"\n[Generated ChangePlan]")
        print(f"  ID: {plan.id}")
        print(f"  Risk (proposed): {plan.risk_level_proposed.value}")
        print(f"  Rollback: {plan.rollback_plan[:60]}...")
        print(f"  Verification: {plan.verification_plan[:60]}...")
        print(f"  Health Checks: {len(plan.health_checks)} checks")

        print(f"\n[State Machine]")
        print(f"  Current State: {context.current_state.value}")
        print(f"  Transitions: {len(context.state_history)}")
        for trans in context.state_history:
            print(f"    {trans['from']} → {trans['to']} ({trans['reason']})")

    print("\n" + "=" * 70)
    print("Key Takeaways")
    print("=" * 70)
    print("1. ✅ Intent decomposition is DETERMINISTIC (rule-based)")
    print("2. ✅ Risk shaping is AUTOMATIC (rollback/verification auto-generated)")
    print("3. ✅ State machine is EXPLICIT (clear transitions)")
    print("4. ✅ Tool routing is CONTROLLED (state → allowed tools)")
    print("5. ✅ Output is STABLE (ChangePlan ready for WriteGate)")
    print("\nBefore Planner:")
    print("  LLM thinking randomly → WriteGate filtering → Low approval rate")
    print("\nAfter Planner:")
    print("  Planner shaping thinking → WriteGate validating → High approval rate")
    print()


if __name__ == "__main__":
    demo_planner_layer()
