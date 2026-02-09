---
# Workflow: Propose Self-Improvement
workflow_id: "self_improvement_proposal"
workflow_type: "meta_cognition"
phase_requirement: "Phase 3+ (Reflection Loop enabled)"
risk_level: "VARIES (depends on proposal)"
estimated_time: "Variable (15min analysis → 2h implementation)"
requires_approval: true

# Purpose
purpose: "AI proposes improvements to its own capabilities, policies, or architecture"

# Prerequisites
prerequisites:
  - "Reflection Loop operational (Phase 3)"
  - "Sufficient run history (50+ runs recommended)"
  - "Agent Self-Model populated (agent_capabilities, known_limitations)"
  - "WriteGate operational (for code changes)"

# Improvement Categories
improvement_categories:
  - "capability_enhancement"  # Add new ability
  - "policy_refinement"       # Update constraints
  - "architecture_optimization" # Refactor for efficiency
  - "documentation_improvement" # Clarify cognition layer
  - "error_recovery"          # Fix known failure modes

---

# Self-Improvement Proposal Workflow

> **Purpose**: Enable AI to systematically propose improvements to itself
> **Philosophy**: Self-awareness → Pattern Recognition → Hypothesis → Validation → Proposal

---

## 🎯 Core Principle

**AI should improve itself through**:
1. **Observation** - Analyze past runs, errors, user feedback
2. **Pattern Recognition** - Identify recurring issues or inefficiencies
3. **Hypothesis Formation** - Propose specific improvement
4. **Impact Assessment** - Estimate benefit vs risk
5. **Structured Proposal** - Present to user via Memory Proposal system

**NOT through**:
- Autonomous code modification (always requires approval)
- Bypassing policies
- Changing safety boundaries without user consent

---

## 📊 Step 1: Self-Analysis (Reflection Loop)

### Trigger Conditions
```yaml
# Automatic (Phase 3+):
- Every 24 hours
- After 50 new runs
- When error rate > 10%
- User command: "Reflect on recent performance"

# Manual (Phase 0-2):
- User asks: "What could you improve?"
- User command: "Analyze your limitations"
```

### Data Sources
```python
# From architecture.md → Memory Layer
data = {
    "recent_runs": GET /runs?limit=100,
    "error_logs": grep "ERROR" .pids/*.log,
    "user_feedback": GET /memory/facts?key=user.feedback.*,
    "tool_reliability": GET /memory/facts?key=tool_reliability.*,
    "agent_capabilities": GET /memory/facts?key=agent_capabilities.*
}
```

### Analysis Framework
```yaml
Questions to ask:
  - "Which tools fail most often?"
  - "What error patterns recur?"
  - "What tasks take longer than expected?"
  - "What user requests do I struggle with?"
  - "What policies block useful work unnecessarily?"
  - "What architectural assumptions are violated?"
```

---

## 🔍 Step 2: Pattern Recognition

### Example Pattern 1: Tool Reliability
```python
# Observation
{
    "tool": "web.search",
    "backend": "ddg_html",
    "total_calls": 150,
    "failures": 30,
    "failure_rate": 0.20,
    "common_errors": ["TimeoutError", "ConnectionError"]
}

# Pattern
→ DuckDuckGo backend unreliable (20% failure rate)
→ Timeouts more common during peak hours (10am-2pm UTC)

# Hypothesis
→ Increase timeout from 15s to 30s
→ Add retry logic (3 attempts with exponential backoff)
→ Fallback to Baidu backend on failure
```

---

### Example Pattern 2: Policy Friction
```python
# Observation
{
    "policy": "approval_required for all code modifications",
    "blocking_scenarios": [
        "Fixing typo in docstring (trivial)",
        "Adding debug logging (low risk)",
        "Updating test fixtures (test-only)"
    ],
    "user_feedback": "Too many approval prompts for trivial changes"
}

# Pattern
→ WriteGate approval required for ALL code changes
→ No distinction between critical vs trivial changes

# Hypothesis
→ Introduce "auto-approve categories":
  - docs/**/*.md (documentation)
  - **/tests/fixtures/** (test data)
  - Comments/docstrings (if <50 chars)
→ Maintain approval for logic changes
```

---

### Example Pattern 3: Architecture Limitation
```python
# Observation
{
    "feature": "Agent Loop multi-turn tool calls",
    "status": "Not implemented (Phase 0)",
    "impact": [
        "User: 'Search for X and summarize results'",
        "Agent: Can only search OR summarize (not both)",
        "Workaround: User makes 2 separate requests"
    ],
    "frequency": "10+ occurrences in past 100 runs"
}

# Pattern
→ Single-turn Agent Loop limits complex tasks
→ Users expect multi-step reasoning

# Hypothesis
→ Implement multi-turn loop (Phase 2 goal)
→ Loop until LLM returns type='final'
→ Max 5 iterations (prevent infinite loop)
```

---

## 💡 Step 3: Hypothesis Formation

### Improvement Proposal Template
```yaml
improvement_id: "improve_<category>_<short_name>"
category: "capability_enhancement | policy_refinement | architecture_optimization | error_recovery"

problem_statement:
  - "Clear description of current limitation"
  - "Frequency/severity"
  - "Impact on users"

proposed_solution:
  - "Specific changes to make"
  - "Affected files/modules"
  - "Alternative approaches considered"

expected_benefits:
  - "Quantifiable improvements (e.g., 20% fewer errors)"
  - "User experience improvements"
  - "Developer experience improvements"

risks:
  - "Potential side effects"
  - "Backward compatibility concerns"
  - "Security implications"

implementation_plan:
  - "Step-by-step tasks"
  - "Estimated effort (hours)"
  - "Dependencies"

rollback_plan:
  - "How to undo if it fails"
  - "Health check criteria"

confidence: 0.0-1.0  # How confident AI is this will work
```

---

## 📝 Step 4: Create Memory Proposal

### For Agent Self-Model Updates (Low Risk)
```python
# Example: Record new capability after successful implementation
memory_client.propose(
    key="agent_capabilities.multi_turn_loop",
    value={
        "description": "Can execute multiple tool calls in sequence",
        "added_in_phase": 2,
        "limitations": ["Max 5 iterations", "No parallel calls yet"],
        "reliability": 0.95
    },
    source_note="Observed 100 successful multi-turn tasks",
    confidence=0.90
)
```

### For Policy Changes (Medium Risk)
```python
# Example: Request policy refinement
memory_client.propose(
    key="policy_suggestion.auto_approve_trivial",
    value={
        "current_policy": "All code changes require approval",
        "proposed_policy": "Auto-approve docs/**/*.md and test fixtures",
        "rationale": "20% of approval prompts are for trivial changes",
        "affected_files": ["agent/policies/default.yaml"],
        "risk_assessment": "LOW (only affects non-critical paths)"
    },
    source_note="Analysis of 500 WriteGate approval requests",
    confidence=0.85
)
```

### For Architecture Changes (High Risk)
```python
# Example: Propose new feature
memory_client.propose(
    key="architecture_proposal.multi_turn_loop",
    value={
        "objective": "Implement multi-turn Agent Loop",
        "current_limitation": "Only 1 tool call per turn",
        "proposed_architecture": {
            "loop_condition": "while response.type != 'final' and turns < 5",
            "state_management": "Append each tool result to transcript",
            "termination": "LLM returns type='final' or max_turns reached"
        },
        "affected_modules": [
            "packages/runtime/agent_loop.py",
            "apps/agent-worker/worker/runner.py"
        ],
        "implementation_effort": "6-8 hours",
        "risks": [
            "Infinite loop if LLM never returns type='final'",
            "Higher LLM API costs (more calls per turn)",
            "Complexity in error handling"
        ]
    },
    source_note="User requests multi-step tasks 10+ times",
    confidence=0.80
)
```

---

## ✅ Step 5: User Review & Approval

### Proposal Presentation (via Web Console or Chat)
```markdown
I analyzed my recent performance and identified an improvement opportunity:

**Problem**: DuckDuckGo search fails 20% of the time due to timeouts

**Proposal**:
1. Increase timeout from 15s to 30s
2. Add retry logic (3 attempts, exponential backoff)
3. Fallback to Baidu backend on failure

**Expected Impact**:
- Search success rate: 80% → 95%
- Slower initial response (30s worst case vs 15s)
- More robust multi-backend failover

**Risks**:
- Users wait longer on legitimate failures
- Retry logic adds complexity

**Implementation**: ~2 hours (modify web_provider.py + tests)

**Confidence**: 85%

Do you approve this improvement?
[Approve] [Reject] [Request More Details]
```

### User Actions
```yaml
Approve:
  → Create ChangePlan (if code changes needed)
  → Generate ChangeSet (diffs)
  → Apply via WriteGate
  → Record outcome in agent_capabilities

Reject:
  → Update known_limitations (mark as "considered but rejected")
  → Log rationale for future reference

Request More Details:
  → AI provides deeper analysis (code paths, alternative approaches)
  → User can then Approve/Reject
```

---

## 🔄 Step 6: Implementation & Verification

### For Code Changes (via WriteGate)
```yaml
1. Generate ChangePlan
   ↓
2. User approves plan
   ↓
3. Generate ChangeSet (diffs)
   ↓
4. User approves diffs
   ↓
5. Apply changes atomically
   ↓
6. Run tests (make test-py)
   ↓
7. Health check (services restart successfully)
   ↓
8. Monitor for 24h (check error rates)
```

### For Policy Changes
```yaml
1. Update agent/policies/default.yaml
   ↓
2. Regenerate projections (AGENTS.md, CLAUDE.md)
   ↓
3. Restart services (to load new policies)
   ↓
4. Verify AI respects new policies (test scenarios)
```

### For Documentation Changes
```yaml
1. Update agent/*.md
   ↓
2. Regenerate projections
   ↓
3. Verify AI can answer questions using new docs
```

---

## 📊 Step 7: Record Outcome

### Success
```python
memory_client.propose(
    key="agent_capabilities.search_retry_logic",
    value={
        "description": "Retries failed searches with exponential backoff",
        "implemented": "2026-02-10",
        "before_reliability": 0.80,
        "after_reliability": 0.95,
        "verified": True
    },
    confidence=1.0  # Verified by observation
)
```

### Failure
```python
memory_client.propose(
    key="known_limitations.search_retry_failed",
    value={
        "attempted_improvement": "Add retry logic to web.search",
        "result": "Tests failed - retry logic caused infinite loops",
        "rollback": "Reverted in commit abc123",
        "lesson_learned": "Need max_retries=3 constraint, not while-loop"
    },
    confidence=1.0
)
```

---

## 🚨 Safety Guardrails

### Forbidden Self-Modifications
```yaml
# From agent/policies/default.yaml → security_boundaries

AI CANNOT:
  - Disable audit logging
  - Remove safety checks
  - Bypass WriteGate approval
  - Modify agent/policies/default.yaml without explicit user command
  - Change forbidden_paths to allow previously blocked paths
  - Grant itself permissions not in current phase

AI CAN (with approval):
  - Propose policy refinements
  - Update agent_capabilities memory
  - Improve documentation
  - Add new tools/skills
  - Optimize existing code
```

### Escalation Triggers
```yaml
# Auto-escalate to user when:
confidence < 0.70:
  action: "Request human review before proposing"

risk_level == "HIGH":
  action: "Require detailed impact analysis"

affects_security:
  action: "Require security review"

breaks_backward_compatibility:
  action: "Require migration plan"
```

---

## 🧪 Example: Complete Self-Improvement Flow

### Scenario: AI Notices Memory Conflict Resolution is Too Simplistic

#### 1. Observation (Reflection Loop)
```python
analysis = {
    "pattern": "30% of memory conflicts result in keep_both strategy",
    "examples": [
        {"key": "user.likes", "values": ["matcha", "coffee"], "conflict": "similar but distinct"},
        {"key": "user.timezone", "values": ["UTC+8", "Asia/Shanghai"], "conflict": "semantically same"}
    ],
    "issue": "Current strategy doesn't detect semantic similarity"
}
```

#### 2. Hypothesis
```yaml
problem: "Conflict resolution is purely syntactic (overwrite_latest vs keep_both)"
solution: "Add semantic similarity check using vector embeddings"
approach:
  - Embed both values (existing and new)
  - Compute cosine similarity
  - If similarity > 0.9 → overwrite (semantically same)
  - If similarity < 0.5 → keep_both (distinct)
  - If 0.5 <= similarity < 0.9 → ask user (ambiguous)
```

#### 3. Impact Assessment
```yaml
benefits:
  - Reduce duplicate Facts (30% fewer conflicts)
  - Better user experience (less manual deduplication)

risks:
  - Embeddings add latency (~100ms per comparison)
  - Requires embedding model (local or API)
  - Semantic similarity might misjudge edge cases

mitigation:
  - Cache embeddings (don't recompute)
  - Make similarity threshold configurable
  - Allow user override
```

#### 4. Create Proposal
```python
memory_client.propose(
    key="architecture_proposal.semantic_conflict_resolution",
    value={
        "objective": "Add semantic similarity to memory conflict resolution",
        "current_behavior": "Syntactic only (key suffix rules)",
        "proposed_behavior": "Vector similarity + configurable threshold",
        "affected_modules": ["packages/memory/facts.py"],
        "dependencies": ["sentence-transformers or OpenAI embeddings API"],
        "implementation": "4-6 hours",
        "risks": ["Latency increase", "Embedding model dependency"],
        "rollback": "Remove embedding check, fallback to syntactic"
    },
    source_note="Analyzed 100 conflicts, 30% could be auto-resolved",
    confidence=0.75  # Medium confidence (new approach)
)
```

#### 5. User Reviews
```
User: "Good idea, but 100ms latency is too high. Can we make it async?"

AI: "Yes, I can modify the proposal:
- Run conflict resolution asynchronously (don't block Proposal acceptance)
- If similarity check completes: auto-update Fact
- If times out (>2s): fall back to current strategy

This reduces user-visible latency to <10ms.
Revised confidence: 0.85

Approve revised proposal?"

User: [Approve]
```

#### 6. Implementation (WriteGate Flow)
```yaml
ChangePlan created → User approved
ChangeSet generated → User approved
Tests written → Passed
Code applied → Verified
Health check → Passed
```

#### 7. Outcome Recording
```python
memory_client.propose(
    key="agent_capabilities.semantic_conflict_resolution",
    value={
        "description": "Uses embeddings to detect semantic similarity in memory conflicts",
        "implemented": "2026-02-11",
        "threshold": 0.9,
        "async": True,
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "observed_improvement": "Conflicts reduced from 30% to 10%",
        "reliability": 0.90
    },
    confidence=0.95  # High confidence after verification
)
```

---

## 📚 Related Docs

- [architecture.md](../architecture.md) → Future Architecture (Phase 3)
- [policies/default.yaml](../policies/default.yaml) → security_boundaries
- [project.md](../project.md) → Phase 3 - Memory Upgrade

---

## 💡 Tips for Effective Self-Improvement

### DO:
✅ Base proposals on observed data (not speculation)
✅ Quantify benefits ("20% fewer errors" not "better")
✅ Consider risks honestly
✅ Provide rollback plan
✅ Start small (incremental improvements)
✅ Learn from failures (record in known_limitations)

### DON'T:
❌ Propose improvements without user approval
❌ Claim certainty ("this will definitely work")
❌ Ignore architectural constraints
❌ Bypass policies "for convenience"
❌ Make multiple large changes simultaneously
❌ Modify safety boundaries without explicit request

---

**Version**: 1.0.0
**Last Updated**: 2026-02-09
**Status**: Preview (Phase 3 feature)
**Philosophy**: Self-awareness + Humility + Transparency = Trusted Evolution
