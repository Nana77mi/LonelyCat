"""
Planner Orchestrator - Main Coordination Layer

Philosophy: Planner shapes thinking, LLM provides reasoning.

Orchestrates:
    1. Intent decomposition (deterministic)
    2. State machine transitions (deterministic)
    3. LLM calls (reasoning only, not workflow decisions)
    4. Risk shaping (deterministic)
    5. ChangePlan generation (structured output)

Output: ChangePlan + ChangeSet (ready for WriteGate)

Key Insight:
- Before: LLM decides everything → unstable
- After: Planner decides workflow, LLM fills reasoning → stable
"""

from typing import Dict, List, Optional, Callable
from datetime import datetime
from pathlib import Path

from .state_machine import (
    PlannerState,
    PlannerStateMachine,
    StateContext,
    TransitionReason,
    create_initial_context
)
from .decomposer import IntentDecomposer, DecomposedIntent
from .risk_shaper import RiskShaper

# Import governance models
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from governance import (
    ChangePlan,
    ChangeSet,
    FileChange,
    Operation,
    RiskLevel,
    generate_plan_id,
    generate_changeset_id
)


class PlannerOrchestrator:
    """
    Main orchestration layer for planning workflow.

    Coordinates:
    - State machine
    - Intent decomposition
    - Risk shaping
    - LLM reasoning (future: Phase 1.5.1)
    """

    def __init__(self):
        """Initialize orchestrator."""
        self.state_machine = PlannerStateMachine()
        self.decomposer = IntentDecomposer()
        self.risk_shaper = RiskShaper()

    def create_plan_from_intent(
        self,
        user_intent: str,
        created_by: str = "planner",
        llm_reasoner: Optional[Callable] = None
    ) -> Dict:
        """
        Main entry point: Convert user intent to ChangePlan + ChangeSet.

        Args:
            user_intent: User request string
            created_by: Who is creating this plan
            llm_reasoner: Optional LLM reasoning function (Phase 1.5.1)

        Returns:
            dict with:
            - context: StateContext
            - decomposed: DecomposedIntent
            - plan: ChangePlan (if generated)
            - changeset: ChangeSet (if generated)
        """
        # Step 1: Create initial context
        context = create_initial_context(user_intent)

        # Step 2: Decompose intent (deterministic)
        decomposed = self.decomposer.decompose(user_intent)

        # Step 3: Decide if we need analysis
        if decomposed.needs_analysis:
            # Transition to ANALYSIS state
            context = self.state_machine.transition(
                context,
                PlannerState.ANALYSIS,
                TransitionReason.NEED_INVESTIGATION
            )

            # Phase 1.5 MVP: Skip actual analysis (would call LLM here)
            # Store analysis requirements for future implementation
            context.analysis_data = {
                "requirements": [req.value for req in decomposed.analysis_requirements],
                "tools": decomposed.analysis_tools,
                "affected_components": decomposed.affected_components
            }

            # Transition to PLAN_GENERATION after "analysis"
            context = self.state_machine.transition(
                context,
                PlannerState.PLAN_GENERATION,
                TransitionReason.SUFFICIENT_INFO
            )
        else:
            # Skip analysis, go straight to planning
            context = self.state_machine.transition(
                context,
                PlannerState.PLAN_GENERATION,
                TransitionReason.SUFFICIENT_INFO
            )

        # Step 4: Generate ChangePlan (with risk shaping)
        plan = self._generate_change_plan(
            context=context,
            decomposed=decomposed,
            created_by=created_by
        )

        context.change_plan_id = plan.id

        # Step 5: Generate ChangeSet (placeholder in Phase 1.5 MVP)
        changeset = self._generate_changeset_placeholder(
            plan_id=plan.id,
            affected_paths=plan.affected_paths,
            generated_by=created_by
        )

        context.changeset_id = changeset.id

        # Step 6: Transition to GOVERNANCE_CHECK
        context = self.state_machine.transition(
            context,
            PlannerState.GOVERNANCE_CHECK,
            TransitionReason.PLAN_READY
        )

        return {
            "context": context,
            "decomposed": decomposed,
            "plan": plan,
            "changeset": changeset
        }

    def _generate_change_plan(
        self,
        context: StateContext,
        decomposed: DecomposedIntent,
        created_by: str
    ) -> ChangePlan:
        """
        Generate ChangePlan with auto-generated safety fields.

        This is where Risk Shaper injects rollback/verification.
        """
        # Auto-generate safety fields
        enhanced = self.risk_shaper.generate_rollback_plan(
            affected_paths=decomposed.affected_components,
            operation_type="modify"
        )

        verification = self.risk_shaper.generate_verification_plan(
            affected_paths=decomposed.affected_components,
            operation_type="modify"
        )

        health_checks = self.risk_shaper.generate_health_checks(
            affected_paths=decomposed.affected_components
        )

        # Map estimated risk to RiskLevel
        risk_mapping = {
            "low": RiskLevel.LOW,
            "medium": RiskLevel.MEDIUM,
            "high": RiskLevel.HIGH
        }
        risk_level = risk_mapping.get(decomposed.estimated_risk, RiskLevel.MEDIUM)

        # Create ChangePlan
        plan = ChangePlan(
            id=generate_plan_id(),
            intent=context.user_intent,
            objective=decomposed.suggested_approach,
            rationale=f"Intent type: {decomposed.intent_type.value}; Affected: {', '.join(decomposed.affected_components)}",
            affected_paths=decomposed.affected_components if decomposed.affected_components else ["<to_be_determined>"],
            risk_level_proposed=risk_level,
            rollback_plan=enhanced,  # Auto-generated!
            verification_plan=verification,  # Auto-generated!
            created_by=created_by,
            created_at=datetime.utcnow(),
            confidence=0.85,  # Planner-generated = high confidence
            health_checks=health_checks,  # Auto-generated!
            policy_refs=["planner_generated"]
        )

        return plan

    def _generate_changeset_placeholder(
        self,
        plan_id: str,
        affected_paths: List[str],
        generated_by: str
    ) -> ChangeSet:
        """
        Generate placeholder ChangeSet.

        Phase 1.5 MVP: Just create empty changeset.
        Phase 1.5.1: LLM will generate actual FileChanges.
        """
        # Create placeholder FileChange
        placeholder_change = FileChange(
            operation=Operation.UPDATE,
            path=affected_paths[0] if affected_paths else "placeholder.py",
            old_content="# Placeholder",
            new_content="# Placeholder (to be generated)",
            diff_unified="",
            line_count_delta=0,
            size_bytes=0
        )

        changeset = ChangeSet(
            id=generate_changeset_id(),
            plan_id=plan_id,
            changes=[placeholder_change],
            checksum="",
            generated_by=generated_by,
            generated_at=datetime.utcnow()
        )

        changeset.compute_checksum()

        return changeset

    def validate_tool_usage(
        self,
        context: StateContext,
        tool_name: str
    ) -> bool:
        """
        Validate if tool can be used in current state.

        Args:
            context: Current state context
            tool_name: Name of tool to validate

        Returns:
            True if tool is allowed

        Raises:
            ValueError: If tool is not allowed
        """
        if not self.state_machine.is_tool_allowed(context.current_state, tool_name):
            allowed = self.state_machine.get_allowed_tools(context.current_state)
            raise ValueError(
                f"Tool '{tool_name}' not allowed in state '{context.current_state.value}'. "
                f"Allowed tools: {allowed}"
            )

        return True

    def get_workflow_summary(self, context: StateContext) -> Dict:
        """
        Get summary of workflow progress.

        Returns:
            dict with current state, history, next steps
        """
        return {
            "current_state": context.current_state.value,
            "user_intent": context.user_intent,
            "state_history": context.state_history,
            "change_plan_id": context.change_plan_id,
            "changeset_id": context.changeset_id,
            "decision_id": context.decision_id,
            "is_terminal": self.state_machine.is_terminal_state(context.current_state)
        }


# ==================== Convenience Functions ====================

def quick_plan(
    user_intent: str,
    created_by: str = "planner"
) -> Dict:
    """
    Quick convenience function to generate plan from intent.

    Args:
        user_intent: User request
        created_by: Creator identifier

    Returns:
        dict with plan, changeset, context
    """
    orchestrator = PlannerOrchestrator()
    return orchestrator.create_plan_from_intent(user_intent, created_by)


def demo_planner_workflow():
    """Demo the planner workflow."""
    print("=" * 60)
    print("Planner Layer Demo - Phase 1.5")
    print("=" * 60)

    # Test different intents
    intents = [
        "Fix memory conflict resolution bug",
        "Add new web search provider",
        "Update documentation for WriteGate",
        "Optimize database query performance"
    ]

    for intent in intents:
        print(f"\n--- Intent: {intent} ---")

        result = quick_plan(intent, created_by="demo")

        context = result["context"]
        decomposed = result["decomposed"]
        plan = result["plan"]

        print(f"Intent Type: {decomposed.intent_type.value}")
        print(f"Needs Analysis: {decomposed.needs_analysis}")
        print(f"Estimated Risk: {decomposed.estimated_risk}")
        print(f"Affected Components: {', '.join(decomposed.affected_components)}")
        print(f"\nGenerated Plan: {plan.id}")
        print(f"  Objective: {plan.objective}")
        print(f"  Risk: {plan.risk_level_proposed.value}")
        print(f"  Rollback: {plan.rollback_plan[:50]}...")
        print(f"  Health Checks: {len(plan.health_checks)}")
        print(f"\nCurrent State: {context.current_state.value}")

    print("\n" + "=" * 60)
    print("Key Takeaway: Planner auto-generates safety fields!")
    print("=" * 60)


if __name__ == "__main__":
    demo_planner_workflow()
