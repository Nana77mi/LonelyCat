---
# Workflow: Debug Memory System Issues
workflow_id: "debug_memory_issue"
workflow_type: "troubleshooting"
phase_requirement: "Phase 0+ (read-only analysis)"
risk_level: "LOW"
estimated_time: "30-60 minutes"
requires_approval: false  # Diagnosis only, fixes require approval

# Common Scenarios
common_scenarios:
  - "Proposal not appearing in UI"
  - "Fact not injected into LLM context"
  - "Conflict resolution behaving unexpectedly"
  - "Audit log missing entries"
  - "Auto-accept not working"

# Diagnostic Tools
diagnostic_tools:
  - "Memory API (GET endpoints)"
  - "Database queries (read-only)"
  - "Log analysis (agent-worker + core-api)"
  - "Architecture knowledge (agent/architecture.md)"

---

# Debug Memory System Issues

> **Purpose**: Diagnose and resolve common Memory/Facts/Proposal problems
> **Principle**: Understand before fixing - trace data flow through all layers

---

## 🎯 Diagnostic Framework

### Layer-Based Analysis

Memory system spans multiple layers (from architecture.md):

```
Layer 4: Memory Layer (packages/memory/)
  ↓
Layer 2: Orchestration (apps/core-api/app/api/memory.py)
  ↓
Layer 3: Execution (apps/agent-worker/worker/memory_gate.py)
  ↓
Layer 5: Infrastructure (SQLite DB)
```

**Diagnostic Strategy**: Trace issue through these layers

---

## 📋 Scenario 1: Proposal Not Appearing in UI

### Symptoms
- Agent says "I'll remember that"
- No Proposal in Web Console
- Database shows Proposal exists

### Root Causes (Most Common)

#### Cause 1A: Proposal Created in Wrong Scope
```yaml
Problem: Proposal has session_id, but UI filters by project_id
Analysis: Check Proposal.scope_hint vs UI filter
```

**Diagnosis**:
```bash
# Check API response
curl http://localhost:5173/memory/proposals | jq '.proposals[] | {id, scope_hint, status}'

# Expected: scope_hint matches UI filter
# If mismatch: Proposal filtered out by UI
```

**Fix**: Update UI filter or Proposal scope_hint

---

#### Cause 1B: Status Already Changed
```yaml
Problem: Proposal auto-accepted (status=accepted), UI only shows pending
Analysis: Check AUTO_ACCEPT env var
```

**Diagnosis**:
```bash
# Check settings
curl http://localhost:5173/settings | jq '.memory'

# Check if AUTO_ACCEPT enabled
printenv | grep MEMORY_AUTO_ACCEPT

# Query all Proposals (not just pending)
curl "http://localhost:5173/memory/proposals?status=accepted" | jq
```

**Fix**: If auto-accept unintended, set `MEMORY_AUTO_ACCEPT=0`

---

#### Cause 1C: TTL Expired
```yaml
Problem: Proposal created with short TTL, already expired
Analysis: Check Proposal.ttl_seconds and created_at
```

**Diagnosis**:
```bash
# Query expired Proposals
curl "http://localhost:5173/memory/proposals?status=expired" | jq

# Check time delta
# created_at + ttl_seconds < now() → expired
```

**Fix**: Increase default TTL in agent-worker config

---

### Diagnostic Flow

```
1. Verify Proposal Created
   ↓ GET /memory/proposals
   ↓ Check DB: SELECT * FROM proposals WHERE status='pending'

2. Check Scope Filter
   ↓ Does scope_hint match UI filter?
   ↓ Global proposals appear in all contexts

3. Check Status
   ↓ Is status='accepted' instead of 'pending'?
   ↓ Check AUTO_ACCEPT settings

4. Check TTL
   ↓ created_at + ttl_seconds > now()?
   ↓ If expired: status='expired'

5. Check UI Logic
   ↓ Read apps/web-console/src/api/conversations.ts
   ↓ Verify API call parameters
```

---

## 📋 Scenario 2: Fact Not Injected into LLM Context

### Symptoms
- Fact status='active' in DB
- Agent doesn't know the information
- LLM responses ignore Fact

### Root Causes

#### Cause 2A: Wrong Scope
```yaml
Problem: Fact is session-scoped, but different conversation_id
Analysis: Check Fact.session_id vs current conversation
```

**Diagnosis**:
```bash
# Get active facts for specific conversation
curl "http://localhost:5173/memory/facts/active?conversation_id=conv_123" | jq

# Check Fact's scope and IDs
SELECT id, key, scope, session_id, status FROM facts WHERE status='active';
```

**From architecture.md**:
```
Active Facts Query:
  - scope='global' (always included)
  - OR scope='session' AND session_id=conversation_id
```

**Fix**: Ensure Fact has correct scope

---

#### Cause 2B: Fact Revoked
```yaml
Problem: Fact was revoked but agent still expects it
Analysis: Check Fact.status and audit_events
```

**Diagnosis**:
```bash
# Check Fact status
SELECT key, value, status, updated_at FROM facts WHERE key='user.likes';

# Check audit log for revocations
SELECT * FROM audit_events
WHERE target_type='fact' AND type='fact.revoked'
ORDER BY created_at DESC LIMIT 10;
```

**Fix**: Reactivate Fact if revocation was accidental

---

#### Cause 2C: Facts Not Fetched
```yaml
Problem: Agent Worker not calling GET /memory/facts/active
Analysis: Check agent-worker logs
```

**Diagnosis**:
```bash
# Check agent-worker logs
Get-Content .pids/agent-worker.log | Select-String "facts/active"

# Expected: "GET /memory/facts/active?conversation_id=..."
# If missing: Agent Worker not fetching Facts
```

**Fix**: Check agent-worker chat_flow.py logic

---

#### Cause 2D: System Message Construction Failed
```yaml
Problem: Facts fetched but not injected into system message
Analysis: Check responder.py logic
```

**Diagnosis**:
```python
# Read the code
Read apps/agent-worker/worker/responder.py

# Look for _build_system_message()
# Should contain:
#   system_message += "\n\n## Active Facts\n"
#   for fact in facts:
#       system_message += f"- {fact['key']}: {fact['value']}\n"
```

**Trace in logs**:
```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Check system message content
grep "system_message" .pids/agent-worker.log
```

---

### Diagnostic Flow

```
1. Verify Fact Exists
   ↓ GET /memory/facts?key=<key>&status=active

2. Check Scope Match
   ↓ Fact.scope='global' OR (scope='session' AND session_id=conv_id)

3. Verify API Call
   ↓ Check logs: GET /memory/facts/active?conversation_id=...

4. Check Response
   ↓ Does API return the Fact?
   ↓ snapshot_id matches?

5. Trace Injection
   ↓ Read responder.py → _build_system_message()
   ↓ Enable debug logging to see constructed message

6. Verify LLM Input
   ↓ Check actual messages sent to LLM
   ↓ Facts in system message?
```

---

## 📋 Scenario 3: Conflict Resolution Not Working

### Symptoms
- Two Facts with same key exist
- Expected overwrite, got keep_both
- Or vice versa

### Root Causes

#### Cause 3A: key_policies Table vs Hardcoded Logic
```yaml
Problem: Mismatch between DB policy and code logic
Analysis: Check key_policies table and _get_key_policy()
```

**From architecture.md**:
```python
# Hardcoded logic (packages/memory/facts.py)
if key.endswith("[]") or key.endswith("_list"):
    return "keep_both"
elif key.startswith("project_") and key.endswith("_goal"):
    return "overwrite_latest"
else:
    # Check key_policies table
    # Default: "overwrite_latest"
```

**Diagnosis**:
```sql
-- Check if key has custom policy
SELECT key, strategy FROM key_policies WHERE key='user.likes';

-- If no row: uses hardcoded logic
-- If row exists: uses strategy from table
```

**Fix**:
- Add explicit policy: `INSERT INTO key_policies VALUES ('user.likes', 'overwrite_latest')`
- Or fix hardcoded logic

---

#### Cause 3B: Proposal Accepted with Wrong Strategy
```yaml
Problem: accept_proposal() called with wrong strategy parameter
Analysis: Check API call parameters
```

**Diagnosis**:
```bash
# Check audit log
SELECT diff_after FROM audit_events
WHERE type='proposal.accepted'
ORDER BY created_at DESC LIMIT 1;

# Look for "strategy" field
# Should be "overwrite_latest" or "keep_both"
```

**From architecture.md**:
```
POST /memory/proposals/{id}/accept
{
  "strategy": "overwrite_latest" | "keep_both",  # Optional
  "scope": "global" | "project" | "session",
  "project_id": "...",  # if scope=project
  "session_id": "..."   # if scope=session
}
```

**Fix**: Call API with correct strategy

---

#### Cause 3C: Multiple Sessions Creating Facts
```yaml
Problem: Two agent instances accepting same Proposal → race condition
Analysis: Check audit log timestamps
```

**Diagnosis**:
```sql
-- Find facts created within 1 second
SELECT key, created_at FROM facts
WHERE key='user.likes'
ORDER BY created_at;

-- If created_at difference < 1s: likely race condition
```

**Fix**: Implement database-level unique constraint (future)

---

## 📋 Scenario 4: Audit Log Missing Entries

### Symptoms
- Operation succeeds but no audit log
- audit_events table empty
- Cannot trace who changed what

### Root Causes

#### Cause 4A: AuditLogger Not Called
```yaml
Problem: Code path bypasses audit_logger.log_event()
Analysis: Check memory.py logic
```

**Diagnosis**:
```python
# Read the code
Read packages/memory/memory.py

# Look for audit_logger.log_event() calls
# Should appear after every state change:
#   - create_proposal()
#   - accept_proposal()
#   - reject_proposal()
#   - revoke_fact()
```

**Fix**: Add missing audit calls

---

#### Cause 4B: Database Transaction Rolled Back
```yaml
Problem: Operation failed, transaction rolled back, audit not committed
Analysis: Check for exceptions in logs
```

**Diagnosis**:
```bash
# Check for errors
grep "ERROR" .pids/core-api.log | grep "memory"

# Check if transaction commit failed
grep "rollback" .pids/core-api.log
```

**Fix**: Ensure audit logging happens in separate transaction (future)

---

## 📋 Scenario 5: Auto-Accept Not Working

### Symptoms
- confidence >= 0.85
- MEMORY_AUTO_ACCEPT=1
- Proposal still pending

### Root Causes

#### Cause 5A: Confidence Check Logic
```yaml
Problem: Confidence compared as string instead of float
Analysis: Check create_proposal() logic
```

**Diagnosis**:
```python
# Check code
Read apps/core-api/app/api/memory.py → create_proposal_endpoint()

# Should have:
if confidence >= float(os.getenv("MEMORY_AUTO_ACCEPT_MIN_CONF", "0.85")):
    # Auto-accept
```

**Fix**: Ensure type coercion

---

#### Cause 5B: Whitelist Check
```yaml
Problem: MEMORY_AUTO_ACCEPT_PREDICATES set, key not in list
Analysis: Check env var
```

**Diagnosis**:
```bash
# Check whitelist
echo $MEMORY_AUTO_ACCEPT_PREDICATES

# If set: only keys in list auto-accept
# If empty/unset: all keys eligible
```

**Fix**: Add key to whitelist or remove whitelist

---

## 🛠️ Debugging Tools

### Tool 1: Memory API Explorer
```bash
# List all Proposals
curl http://localhost:5173/memory/proposals | jq

# Filter by status
curl "http://localhost:5173/memory/proposals?status=pending" | jq

# List all Facts
curl http://localhost:5173/memory/facts | jq

# Get active Facts for conversation
curl "http://localhost:5173/memory/facts/active?conversation_id=conv_123" | jq

# Query audit log
curl "http://localhost:5173/memory/audit?target_type=fact&limit=20" | jq
```

---

### Tool 2: Direct Database Queries
```sql
-- Connect to DB
sqlite3 lonelycat_memory.db

-- Query proposals
SELECT id, payload_key, status, confidence, scope_hint, created_at
FROM proposals
ORDER BY created_at DESC LIMIT 10;

-- Query facts
SELECT id, key, value, scope, status, version, updated_at
FROM facts
WHERE status='active'
ORDER BY updated_at DESC LIMIT 10;

-- Query audit events
SELECT id, type, target_type, target_id, created_at
FROM audit_events
ORDER BY created_at DESC LIMIT 20;

-- Find conflicts (multiple active facts with same key)
SELECT key, COUNT(*) as count
FROM facts
WHERE status='active'
GROUP BY key
HAVING count > 1;
```

---

### Tool 3: Log Analysis
```bash
# Core API logs
Get-Content .pids/core-api.log -Tail 100 | Select-String "memory"

# Agent Worker logs
Get-Content .pids/agent-worker.log -Tail 100 | Select-String "proposal\|fact"

# Search for errors
grep -i "error\|exception" .pids/*.log
```

---

## 🔍 General Debugging Checklist

- [ ] Check architecture.md for expected behavior
- [ ] Verify operation succeeded (status code 200)
- [ ] Check database state (Proposal/Fact exists)
- [ ] Verify scope matches context (global/project/session)
- [ ] Check audit log (operation recorded)
- [ ] Review logs for errors/warnings
- [ ] Trace data flow through layers
- [ ] Compare actual vs expected (from architecture)

---

## 🚨 When to Escalate

**Escalate to User When**:
- Data corruption suspected (audit log inconsistent)
- Database migration needed
- Architectural change required (e.g., add unique constraint)
- Security issue found (e.g., audit bypass)

**Example Escalation**:
> "I found a potential race condition in memory conflict resolution:
> - Two agents can accept the same Proposal simultaneously
> - Results in duplicate Facts with same key
> - Architecture assumes atomic acceptance
>
> Suggested fix: Add database-level unique constraint on (scope, key, status='active')
> Risk: Requires migration + may break existing code
>
> Should I create a ChangePlan for this?"

---

## 📚 Related Docs

- [architecture.md](../architecture.md) → MEMORY MODEL
- [architecture.md](../architecture.md) → DATA FLOW → Flow 2
- [project.md](../project.md) → Memory System section
- [docs/spec/memory-spec-v0.md](../../docs/spec/memory-spec-v0.md)

---

**Version**: 1.0.0
**Last Updated**: 2026-02-09
**Methodology**: Layer-based analysis (from architecture)
