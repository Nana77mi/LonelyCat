"""
LonelyCat Planner Layer - Decision Orchestrator

Philosophy: Planner shapes thinking, Governance validates.

NOT an agent. This is a deterministic orchestration layer that:
- Decomposes user intent into stages
- Routes tools based on stage (not LLM whim)
- Auto-generates safety fields (rollback, verification)
- Produces stable ChangePlan + ChangeSet

Architecture:
    User Intent
        ↓
    Planner (deterministic orchestration)
        ↓
    LLM (reasoning engine only)
        ↓
    ChangePlan + ChangeSet
        ↓
    WriteGate (governance validation)

Key Insight: Without Planner, Executor = raw power (dangerous).
"""

from .state_machine import (
    PlannerState,
    TransitionReason,
    PlannerStateMachine,
    StateContext,
    create_initial_context
)

from .risk_shaper import RiskShaper

from .decomposer import (
    IntentDecomposer,
    IntentType,
    AnalysisRequirement,
    DecomposedIntent
)

from .orchestrator import PlannerOrchestrator

__all__ = [
    # State Machine
    "PlannerState",
    "TransitionReason",
    "PlannerStateMachine",
    "StateContext",
    "create_initial_context",

    # Risk Shaping
    "RiskShaper",

    # Intent Decomposition
    "IntentDecomposer",
    "IntentType",
    "AnalysisRequirement",
    "DecomposedIntent",

    # Orchestrator
    "PlannerOrchestrator"
]

__version__ = "1.0.0"
