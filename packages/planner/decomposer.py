"""
Intent Decomposer - Break down user intent into stages

Philosophy: Decompose intent deterministically, not emergently.

Takes user request like:
    "Fix memory conflict resolution bug"

Decomposes into stages:
    1. ANALYSIS: Understand current conflict resolution logic
    2. PLAN_GENERATION: Design fix with semantic similarity
    3. GOVERNANCE_CHECK: Validate with WriteGate
    4. EXECUTION_READY: Wait for execution

This is NOT an LLM prompt. This is rule-based decomposition.
"""

from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum


class IntentType(Enum):
    """Classification of user intent."""
    FIX_BUG = "fix_bug"              # Fix existing issue
    ADD_FEATURE = "add_feature"      # Add new functionality
    REFACTOR = "refactor"            # Improve code structure
    UPDATE_DOCS = "update_docs"      # Documentation changes
    ADD_TEST = "add_test"            # Add test coverage
    INVESTIGATE = "investigate"      # Understand/debug only
    OPTIMIZE = "optimize"            # Performance improvements
    UNKNOWN = "unknown"              # Cannot classify


class AnalysisRequirement(Enum):
    """What analysis is needed."""
    READ_CODE = "read_code"          # Need to read implementation
    SEARCH_PATTERN = "search_pattern" # Need to grep for patterns
    TRACE_FLOW = "trace_flow"        # Need to understand data flow
    CHECK_TESTS = "check_tests"      # Need to find existing tests
    REVIEW_DOCS = "review_docs"      # Need to read architecture
    NONE = "none"                    # Skip analysis (intent is clear)


@dataclass
class DecomposedIntent:
    """Result of intent decomposition."""
    original_intent: str
    intent_type: IntentType

    # Stages
    needs_analysis: bool
    analysis_requirements: List[AnalysisRequirement]

    # Planning hints
    suggested_approach: str          # High-level approach
    affected_components: List[str]   # Which parts of codebase
    estimated_risk: str              # "low" | "medium" | "high"

    # Tool routing hints
    analysis_tools: List[str]        # Tools needed in ANALYSIS stage
    planning_tools: List[str]        # Tools needed in PLAN_GENERATION stage


class IntentDecomposer:
    """
    Decomposes user intent into planning stages.

    Uses rule-based logic + keyword matching.
    NOT emergent behavior.
    """

    # Keywords for intent classification
    INTENT_KEYWORDS = {
        IntentType.FIX_BUG: [
            "fix", "bug", "broken", "error", "issue", "problem",
            "doesn't work", "not working", "fails"
        ],
        IntentType.ADD_FEATURE: [
            "add", "create", "implement", "build", "new feature",
            "support for", "enable"
        ],
        IntentType.REFACTOR: [
            "refactor", "restructure", "reorganize", "clean up",
            "improve structure", "simplify"
        ],
        IntentType.UPDATE_DOCS: [
            "update docs", "documentation", "readme", "comment",
            "explain", "document"
        ],
        IntentType.ADD_TEST: [
            "add test", "test coverage", "unit test", "integration test",
            "test for"
        ],
        IntentType.INVESTIGATE: [
            "investigate", "understand", "why", "how does", "debug",
            "trace", "explore"
        ],
        IntentType.OPTIMIZE: [
            "optimize", "performance", "speed up", "make faster",
            "reduce latency", "improve efficiency"
        ]
    }

    # Component keywords
    COMPONENT_KEYWORDS = {
        "memory": ["memory", "facts", "proposal", "conflict"],
        "governance": ["governance", "writegate", "changeplan", "approval"],
        "agent": ["agent", "planner", "orchestrator"],
        "api": ["api", "endpoint", "rest", "http"],
        "database": ["database", "db", "schema", "migration"],
        "ui": ["ui", "frontend", "web-console", "interface"]
    }

    def __init__(self):
        """Initialize decomposer."""
        pass

    def decompose(self, user_intent: str) -> DecomposedIntent:
        """
        Decompose user intent into stages.

        Args:
            user_intent: Raw user request string

        Returns:
            DecomposedIntent with stages and requirements
        """
        intent_lower = user_intent.lower()

        # 1. Classify intent type
        intent_type = self._classify_intent(intent_lower)

        # 2. Determine if analysis is needed
        needs_analysis = self._needs_analysis(intent_type, intent_lower)

        # 3. Determine analysis requirements
        analysis_requirements = self._determine_analysis_requirements(
            intent_type, intent_lower
        ) if needs_analysis else []

        # 4. Suggest approach
        suggested_approach = self._suggest_approach(intent_type, intent_lower)

        # 5. Identify affected components
        affected_components = self._identify_components(intent_lower)

        # 6. Estimate risk
        estimated_risk = self._estimate_risk(intent_type, affected_components)

        # 7. Route tools
        analysis_tools = self._get_analysis_tools(analysis_requirements)
        planning_tools = self._get_planning_tools(intent_type)

        return DecomposedIntent(
            original_intent=user_intent,
            intent_type=intent_type,
            needs_analysis=needs_analysis,
            analysis_requirements=analysis_requirements,
            suggested_approach=suggested_approach,
            affected_components=affected_components,
            estimated_risk=estimated_risk,
            analysis_tools=analysis_tools,
            planning_tools=planning_tools
        )

    # ==================== Classification ====================

    def _classify_intent(self, intent_lower: str) -> IntentType:
        """Classify intent based on keywords."""
        scores = {}

        for intent_type, keywords in self.INTENT_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in intent_lower)
            if score > 0:
                scores[intent_type] = score

        if not scores:
            return IntentType.UNKNOWN

        # Return highest scoring type
        return max(scores, key=scores.get)

    def _identify_components(self, intent_lower: str) -> List[str]:
        """Identify which components are mentioned."""
        components = []

        for component, keywords in self.COMPONENT_KEYWORDS.items():
            if any(kw in intent_lower for kw in keywords):
                components.append(component)

        return components

    # ==================== Analysis Requirements ====================

    def _needs_analysis(self, intent_type: IntentType, intent_lower: str) -> bool:
        """Determine if analysis stage is needed."""
        # Always need analysis for these
        if intent_type in {
            IntentType.FIX_BUG,
            IntentType.REFACTOR,
            IntentType.OPTIMIZE,
            IntentType.INVESTIGATE
        }:
            return True

        # Maybe need analysis
        if intent_type == IntentType.ADD_FEATURE:
            # Need analysis if modifying existing code
            modify_keywords = ["to", "in", "for", "on"]
            return any(kw in intent_lower for kw in modify_keywords)

        # Skip analysis for docs/tests (usually clear intent)
        if intent_type in {IntentType.UPDATE_DOCS, IntentType.ADD_TEST}:
            return False

        return True  # Default: need analysis

    def _determine_analysis_requirements(
        self,
        intent_type: IntentType,
        intent_lower: str
    ) -> List[AnalysisRequirement]:
        """Determine what analysis is needed."""
        requirements = []

        if intent_type == IntentType.FIX_BUG:
            requirements.extend([
                AnalysisRequirement.READ_CODE,
                AnalysisRequirement.TRACE_FLOW,
                AnalysisRequirement.CHECK_TESTS
            ])

        elif intent_type == IntentType.ADD_FEATURE:
            requirements.extend([
                AnalysisRequirement.READ_CODE,
                AnalysisRequirement.REVIEW_DOCS
            ])

        elif intent_type == IntentType.REFACTOR:
            requirements.extend([
                AnalysisRequirement.READ_CODE,
                AnalysisRequirement.CHECK_TESTS
            ])

        elif intent_type == IntentType.INVESTIGATE:
            requirements.extend([
                AnalysisRequirement.READ_CODE,
                AnalysisRequirement.SEARCH_PATTERN,
                AnalysisRequirement.TRACE_FLOW
            ])

        elif intent_type == IntentType.OPTIMIZE:
            requirements.extend([
                AnalysisRequirement.READ_CODE,
                AnalysisRequirement.TRACE_FLOW
            ])

        return requirements

    # ==================== Approach Suggestion ====================

    def _suggest_approach(
        self,
        intent_type: IntentType,
        intent_lower: str
    ) -> str:
        """Suggest high-level approach."""
        if intent_type == IntentType.FIX_BUG:
            return "Identify root cause → Design fix → Test → Apply"

        elif intent_type == IntentType.ADD_FEATURE:
            return "Understand requirements → Design API → Implement → Test"

        elif intent_type == IntentType.REFACTOR:
            return "Understand current structure → Design target → Refactor → Verify tests pass"

        elif intent_type == IntentType.UPDATE_DOCS:
            return "Read existing docs → Update content → Verify formatting"

        elif intent_type == IntentType.ADD_TEST:
            return "Identify test gaps → Write test cases → Verify coverage"

        elif intent_type == IntentType.INVESTIGATE:
            return "Read code → Trace execution → Document findings"

        elif intent_type == IntentType.OPTIMIZE:
            return "Profile performance → Identify bottleneck → Optimize → Benchmark"

        return "Analyze → Plan → Execute → Verify"

    # ==================== Risk Estimation ====================

    def _estimate_risk(
        self,
        intent_type: IntentType,
        affected_components: List[str]
    ) -> str:
        """Estimate risk level based on intent and components."""
        # High risk components
        if any(c in affected_components for c in ["governance", "database"]):
            return "high"

        # High risk operations
        if intent_type in {IntentType.REFACTOR, IntentType.OPTIMIZE}:
            return "medium"

        # Low risk operations
        if intent_type in {IntentType.UPDATE_DOCS, IntentType.ADD_TEST}:
            return "low"

        # Default
        if intent_type == IntentType.FIX_BUG:
            return "medium"

        return "medium"

    # ==================== Tool Routing ====================

    def _get_analysis_tools(
        self,
        requirements: List[AnalysisRequirement]
    ) -> List[str]:
        """Get tools needed for analysis stage."""
        tools = set()

        for req in requirements:
            if req == AnalysisRequirement.READ_CODE:
                tools.update(["read_file", "list_directory"])

            elif req == AnalysisRequirement.SEARCH_PATTERN:
                tools.update(["grep", "glob"])

            elif req == AnalysisRequirement.TRACE_FLOW:
                tools.update(["read_file", "grep"])

            elif req == AnalysisRequirement.CHECK_TESTS:
                tools.update(["glob", "read_file"])

            elif req == AnalysisRequirement.REVIEW_DOCS:
                tools.update(["read_file"])

        return list(tools)

    def _get_planning_tools(self, intent_type: IntentType) -> List[str]:
        """Get tools needed for planning stage."""
        # Planning stage mostly uses data from analysis
        # Plus diff generation
        return ["generate_diff", "compute_checksum"]
