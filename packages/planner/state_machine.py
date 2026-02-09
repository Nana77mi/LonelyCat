"""
Planner State Machine - Deterministic Workflow Orchestration

Manages the lifecycle of a planning request from intent to execution-ready.

State Flow:
    INTENT → ANALYSIS → PLAN_GENERATION → GOVERNANCE_CHECK → EXECUTION_READY

Philosophy:
- States are deterministic (not emergent)
- Transitions have clear rules
- Each state restricts available tools (safety)
"""

from enum import Enum
from typing import List, Optional, Dict, Set
from dataclasses import dataclass
from datetime import datetime


class PlannerState(Enum):
    """Planning workflow states."""
    INTENT = "intent"                   # Initial user request
    ANALYSIS = "analysis"               # Read-only investigation
    PLAN_GENERATION = "plan_generation" # Generate ChangePlan
    GOVERNANCE_CHECK = "governance_check" # WriteGate evaluation
    EXECUTION_READY = "execution_ready" # Approved, ready to execute
    COMPLETED = "completed"             # Execution finished
    FAILED = "failed"                   # Unrecoverable error


class TransitionReason(Enum):
    """Reasons for state transitions."""
    # INTENT → ANALYSIS
    NEED_INVESTIGATION = "need_investigation"  # Need to understand codebase

    # ANALYSIS → PLAN_GENERATION
    SUFFICIENT_INFO = "sufficient_info"  # Enough context collected

    # PLAN_GENERATION → GOVERNANCE_CHECK
    PLAN_READY = "plan_ready"  # ChangePlan + ChangeSet generated

    # GOVERNANCE_CHECK → EXECUTION_READY
    APPROVED = "approved"  # WriteGate returned ALLOW or approval granted

    # GOVERNANCE_CHECK → PLAN_GENERATION
    REJECTED = "rejected"  # WriteGate returned DENY, need to revise
    NEEDS_REVISION = "needs_revision"  # WriteGate NEED_APPROVAL, user wants changes

    # EXECUTION_READY → COMPLETED
    EXECUTION_SUCCESS = "execution_success"

    # * → FAILED
    UNRECOVERABLE_ERROR = "unrecoverable_error"


@dataclass
class StateContext:
    """Context carried through state transitions."""
    user_intent: str
    current_state: PlannerState

    # Analysis phase data
    analysis_data: Dict = None  # Code understanding, architecture info

    # Planning phase data
    change_plan_id: Optional[str] = None
    changeset_id: Optional[str] = None

    # Governance phase data
    decision_id: Optional[str] = None
    approval_id: Optional[str] = None

    # Metadata
    created_at: datetime = None
    updated_at: datetime = None

    # History
    state_history: List[Dict] = None  # Track state transitions

    def __post_init__(self):
        if self.analysis_data is None:
            self.analysis_data = {}
        if self.state_history is None:
            self.state_history = []
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.updated_at is None:
            self.updated_at = datetime.utcnow()


class PlannerStateMachine:
    """
    State machine for planning workflow.

    Enforces:
    - Valid state transitions
    - Tool restrictions per state
    - Safety boundaries
    """

    # Define valid transitions
    VALID_TRANSITIONS = {
        PlannerState.INTENT: {
            PlannerState.ANALYSIS,  # Normal flow: need to investigate
            PlannerState.PLAN_GENERATION,  # Skip analysis if intent is clear
            PlannerState.FAILED
        },
        PlannerState.ANALYSIS: {
            PlannerState.PLAN_GENERATION,  # Collected enough info
            PlannerState.ANALYSIS,  # Stay in analysis (more investigation)
            PlannerState.FAILED
        },
        PlannerState.PLAN_GENERATION: {
            PlannerState.GOVERNANCE_CHECK,  # Plan ready
            PlannerState.ANALYSIS,  # Need more info
            PlannerState.FAILED
        },
        PlannerState.GOVERNANCE_CHECK: {
            PlannerState.EXECUTION_READY,  # Approved
            PlannerState.PLAN_GENERATION,  # Needs revision
            PlannerState.FAILED
        },
        PlannerState.EXECUTION_READY: {
            PlannerState.COMPLETED,  # Success
            PlannerState.FAILED
        },
        PlannerState.COMPLETED: set(),  # Terminal state
        PlannerState.FAILED: set()  # Terminal state
    }

    # Tool restrictions per state (safety)
    ALLOWED_TOOLS = {
        PlannerState.INTENT: {
            # No tools in INTENT state (just parsing)
        },
        PlannerState.ANALYSIS: {
            # Read-only tools
            "read_file",
            "list_directory",
            "grep",
            "glob",
            "web.search",
            "web.fetch",
            "memory.list_facts",
            "memory.query"
        },
        PlannerState.PLAN_GENERATION: {
            # Same as ANALYSIS + planning tools
            "read_file",
            "list_directory",
            "grep",
            "glob",
            "generate_diff",
            "compute_checksum"
        },
        PlannerState.GOVERNANCE_CHECK: {
            # Only governance API calls
            "governance.evaluate",
            "governance.get_decision"
        },
        PlannerState.EXECUTION_READY: {
            # Will be restricted to Phase 2 Executor
            # (No tools allowed from Planner at this stage)
        },
        PlannerState.COMPLETED: set(),
        PlannerState.FAILED: set()
    }

    def __init__(self):
        """Initialize state machine."""
        pass

    def can_transition(
        self,
        from_state: PlannerState,
        to_state: PlannerState
    ) -> bool:
        """
        Check if transition is valid.

        Args:
            from_state: Current state
            to_state: Target state

        Returns:
            True if transition is allowed
        """
        return to_state in self.VALID_TRANSITIONS.get(from_state, set())

    def transition(
        self,
        context: StateContext,
        to_state: PlannerState,
        reason: TransitionReason
    ) -> StateContext:
        """
        Transition to new state.

        Args:
            context: Current context
            to_state: Target state
            reason: Reason for transition

        Returns:
            Updated context

        Raises:
            ValueError: If transition is invalid
        """
        if not self.can_transition(context.current_state, to_state):
            raise ValueError(
                f"Invalid transition: {context.current_state.value} → {to_state.value}"
            )

        # Record transition in history
        context.state_history.append({
            "from": context.current_state.value,
            "to": to_state.value,
            "reason": reason.value,
            "timestamp": datetime.utcnow().isoformat()
        })

        # Update state
        context.current_state = to_state
        context.updated_at = datetime.utcnow()

        return context

    def is_tool_allowed(
        self,
        state: PlannerState,
        tool_name: str
    ) -> bool:
        """
        Check if tool is allowed in current state.

        Args:
            state: Current state
            tool_name: Name of tool to check

        Returns:
            True if tool is allowed
        """
        allowed_tools = self.ALLOWED_TOOLS.get(state, set())

        # Check exact match
        if tool_name in allowed_tools:
            return True

        # Check prefix match (e.g., "memory.list_facts" matches "memory.*")
        for allowed in allowed_tools:
            if allowed.endswith(".*"):
                prefix = allowed[:-2]
                if tool_name.startswith(prefix):
                    return True

        return False

    def get_allowed_tools(self, state: PlannerState) -> Set[str]:
        """Get all allowed tools for a state."""
        return self.ALLOWED_TOOLS.get(state, set())

    def is_terminal_state(self, state: PlannerState) -> bool:
        """Check if state is terminal (no outgoing transitions)."""
        return len(self.VALID_TRANSITIONS.get(state, set())) == 0


# Helper functions

def create_initial_context(user_intent: str) -> StateContext:
    """Create initial context for planning workflow."""
    return StateContext(
        user_intent=user_intent,
        current_state=PlannerState.INTENT
    )


def is_workflow_complete(context: StateContext) -> bool:
    """Check if workflow is in terminal state."""
    return context.current_state in {
        PlannerState.COMPLETED,
        PlannerState.FAILED
    }
