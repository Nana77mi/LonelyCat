# Execute ChangeSet Workflow

**Status**: MANDATORY ENFORCED
**Version**: 1.0.0
**Last Updated**: 2026-02-09

## Overview

This workflow defines the **ONLY ALLOWED PATH** for executing code changes in LonelyCat.
Any attempt to bypass this workflow is a **GOVERNANCE VIOLATION** and will be blocked.

---

## The Only Valid Execution Path

```
1. Intent Decomposition
      ↓
2. Planner Generates ChangePlan + ChangeSet
      ↓
3. WriteGate Evaluation → GovernanceDecision
      ↓
4. Decision Check: ALLOW or (NEED_APPROVAL + human approved)
      ↓
5. Executor Applies ChangeSet (atomic + rollback-safe)
      ↓
6. Verification + Health Checks
      ↓
7. Audit Trail Recorded
```

---

## Mandatory Rules

### Rule 1: No Direct File Writes
**NEVER** write files directly without going through this workflow.

❌ **FORBIDDEN**:
- Direct file.write()
- Manual git commit without evaluation
- Bypassing WriteGate
- Skipping checksum verification

✅ **REQUIRED**:
- All changes MUST be wrapped in ChangeSet
- All ChangeSets MUST pass WriteGate evaluation
- All executions MUST go through HostExecutor

---

### Rule 2: Evaluation Before Execution
**MUST** obtain GovernanceDecision before any file modification.

```python
# REQUIRED SEQUENCE
decision = writegate.evaluate(plan, changeset)

if decision.verdict == Verdict.ALLOW:
    executor.execute(plan, changeset, decision)
elif decision.verdict == Verdict.NEED_APPROVAL:
    # Wait for human approval
    pass
else:  # DENY
    # STOP - do not execute
    raise GovernanceViolation(decision.reasons)
```

---

### Rule 3: Checksum Verification
**MUST** verify ChangeSet integrity before execution.

```python
# REQUIRED CHECK
if not changeset.verify_checksum():
    raise SecurityViolation("ChangeSet tampered - checksum mismatch")
```

---

### Rule 4: Atomic Execution with Rollback
**MUST** execute atomically with automatic rollback on failure.

```python
try:
    backup = create_backup()
    apply_changes()
    verify()
    health_check()
except Exception:
    rollback(backup)  # MANDATORY
    raise
```

---

### Rule 5: Audit Trail
**MUST** record all executions to audit trail.

Required fields:
- `plan_id`
- `changeset_id`
- `decision_id`
- `execution_id`
- `started_at`
- `completed_at`
- `status` (COMPLETED / FAILED / ROLLED_BACK)
- `files_changed`
- `verification_results`

---

## Forbidden Bypasses

### ❌ DO NOT:
1. **Bypass WriteGate**
   - "Just this once, I'll skip evaluation..."
   - NO. Every change goes through governance.

2. **Skip Verification**
   - "The change is simple, no need to verify..."
   - NO. Verification is mandatory for safety.

3. **Ignore Decision**
   - "WriteGate said NEED_APPROVAL but I'll execute anyway..."
   - NO. Respect governance decisions.

4. **Modify ChangeSet After Approval**
   - "I'll just tweak this file real quick..."
   - NO. Any change invalidates the checksum and approval.

5. **Skip Rollback on Failure**
   - "The system will recover eventually..."
   - NO. Rollback is mandatory for consistency.

---

## Decision Flow

```
GovernanceDecision.verdict:

  ALLOW:
    → Execute immediately
    → Record audit trail

  NEED_APPROVAL:
    → Present to human
    → Wait for approval
    → If approved: Execute
    → If denied: STOP

  DENY:
    → STOP immediately
    → Log denial reasons
    → Do NOT execute
```

---

## Execution Constraints

### Concurrency
- **Only ONE execution at a time per repository**
- Use ExecutionLock (repo-level mutex)
- Concurrent attempts MUST wait or fail

### Idempotency
- **Same ChangeSet MUST NOT execute twice**
- Use `execution_id = hash(plan_id + changeset.checksum)`
- Already-executed ChangeSets return cached result

### Timeout
- **Every step has timeout**
- Default: 5 minutes per step
- Timeout triggers automatic rollback

### Scope
- **Only touch declared paths**
- `affected_paths` in ChangePlan is the boundary
- Attempts to modify other paths MUST fail

---

## Failure Handling

### On Failure:
1. **STOP immediately** - no partial application
2. **Rollback** - restore from backup
3. **Record failure** - audit trail with error details
4. **Clean up** - remove temp files, release locks
5. **Report** - return ExecutionResult with failure details

### Never:
- Leave partial changes
- Skip cleanup
- Silently fail
- Retry without human approval

---

## Security Boundaries

### Double Verification:
1. **WriteGate** checks before execution
2. **Executor** verifies again during execution
   - Checksum match
   - Path boundaries
   - File content match (for UPDATE)

### Defense in Depth:
- Even if WriteGate is bypassed (should be impossible), Executor defends
- Even if Executor is called directly, it requires valid Decision with ALLOW verdict
- Even if Decision is forged, checksum verification will fail

---

## Example: Valid Execution

```python
from planner import PlannerOrchestrator
from governance import WriteGate
from executor import HostExecutor

# Step 1: Plan
planner = PlannerOrchestrator()
result = planner.create_plan_from_intent(
    user_intent="Fix typo in README",
    created_by="user123"
)
plan = result["plan"]
changeset = result["changeset"]

# Step 2: Evaluate
writegate = WriteGate()
decision = writegate.evaluate(plan, changeset)

# Step 3: Check Decision
if not decision.is_approved():
    print(f"Blocked: {decision.verdict} - {decision.reasons}")
    return

# Step 4: Execute
executor = HostExecutor(workspace_root)
exec_result = executor.execute(plan, changeset, decision)

# Step 5: Check Result
if exec_result.success:
    print(f"✓ Executed: {exec_result.files_changed} files changed")
else:
    print(f"✗ Failed: {exec_result.message}")
    if exec_result.context.rolled_back:
        print("Changes were rolled back")
```

---

## Compliance

This workflow is **ENFORCED** by:
- WriteGate policy engine
- Executor approval validation
- Checksum verification
- Audit trail requirements

**Violations will be:**
- Logged to audit trail
- Blocked at runtime
- Reported to operators

---

## Version History

- **1.0.0** (2026-02-09): Initial workflow definition for Phase 2
