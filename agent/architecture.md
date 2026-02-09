---
# Machine-Readable Metadata
document_type: "architecture"
target_audience: "ai_agents"
purpose: "cognition_index"
ai_role: "architecture_reference"
write_access: "restricted"
modification_protocol: "writegate_required"
version: "0.1.0"
last_updated: "2026-02-09"

# Key Architectural Invariants (DO NOT VIOLATE)
invariants:
  - "Memory changes must go through Proposal → Acceptance flow"
  - "Skills execute in Docker sandbox with --network=none"
  - "All state changes must be audited in audit_events table"
  - "Core API never calls LLM directly (delegate to agent-worker)"
  - "Facts are scoped: global OR project OR session"

# Critical Paths (Where things actually happen)
critical_modules:
  agent_loop: "packages/runtime/agent_loop.py"
  memory_store: "packages/memory/memory.py"
  tool_runtime: "apps/agent-worker/worker/tools/runtime.py"
  writegate: "TBD - Phase 1"
  sandbox_executor: "apps/core-api/app/api/sandbox.py"

---

# LonelyCat Architecture Reference

> **For AI Agents**: This document is your structural map of LonelyCat.
> Read this to understand **how components relate**, not implementation details.

---

## 🏗️ META: System Identity

**What LonelyCat Is**:
- Self-describing agent platform (reads `agent/` to understand itself)
- Local-first (SQLite + Docker, no cloud dependency)
- Multi-layer (Cognition → Orchestration → Execution → Memory → Infrastructure)

**What LonelyCat Is NOT**:
- Not a single monolithic app (microservices: core-api + agent-worker + connectors)
- Not stateless (Memory layer persists Facts across sessions)
- Not cloud-hosted (runs entirely on user's machine)

**Core Design Philosophy**:
```
AI proposes → Human approves → System executes → Audit records → AI reflects
```

---

## 🎯 LAYERS: 5-Tier Architecture

### Layer 1: Cognitive Layer (Phase 0 - Current)

**Location**: `agent/` directory

**Purpose**: AI's self-awareness - where agents read to understand the project

**Components**:
- `project.md` - Goals, status, roadmap
- `architecture.md` - This file (structural map)
- `policies/` - Safety constraints (what AI cannot do)
- `workflows/` - Task procedures (how to accomplish goals)
- `projections/` - Code snapshots (where to find implementations)

**Key Principle**: Single source of truth → projected to `AGENTS.md`, `CLAUDE.md`, etc.

---

### Layer 2: Orchestration Layer

**Location**: `apps/core-api/`

**Purpose**: Decision-making, policy enforcement, task scheduling

**Core Responsibilities**:
1. **Agent Loop Coordination** - Manages conversation turns
2. **WriteGate** (Phase 1) - Approves/rejects code modifications
3. **Planner** (Phase 3) - Breaks complex tasks into steps
4. **Policy Engine** - Enforces tool usage rules

**Key Modules**:
```
app/api/conversations.py    → Conversation CRUD
app/api/runs.py              → Async task orchestration
app/api/memory.py            → Proposal/Fact management
app/api/settings.py          → Configuration management
app/services/agent_decision.py → LLM decision routing
```

**Critical Invariant**:
- Core API **never executes tools directly**
- Core API **never calls LLM directly**
- All execution delegated to Layer 3

---

### Layer 3: Execution Layer

**Location**: `apps/agent-worker/` + `apps/core-api/app/api/sandbox.py`

**Purpose**: Actually DO things (call LLM, run tools, execute code)

**Components**:

#### A. Agent Worker (LLM Execution)
```
worker/main.py              → Background worker (polls for Runs)
worker/runner.py            → Executes different Run types
worker/tools/runtime.py     → Tool invocation engine
worker/tools/catalog.py     → Multi-provider tool aggregation
worker/tools/web_provider.py → Web search/fetch
worker/tools/mcp_provider.py → MCP protocol adapter
worker/tools/skills_provider.py → Skills invocation
```

#### B. Sandbox Executor (Code Execution)
```
app/api/sandbox.py          → Docker CLI wrapper
app/services/sandbox/runner_docker.py → Execution logic
app/services/sandbox/path_adapter.py  → Win/WSL path translation
```

**Key Principle**: All execution is **sandboxed** or **policy-checked**

---

### Layer 4: Memory Layer

**Location**: `packages/memory/`

**Purpose**: Long-term knowledge persistence + audit trail

**Core Entities**:

#### Proposal (Candidate Memory)
```python
status: pending | accepted | rejected | expired
payload: {key: str, value: Any, tags: List[str]}
confidence: float (0.0-1.0)
scope_hint: global | project | session
```

#### Fact (Accepted Knowledge)
```python
status: active | revoked | archived
key: str  # unique per (scope, key)
value: Any
scope: global | project | session
version: int (auto-increment on update)
```

#### Audit Event (Immutable Log)
```python
type: proposal.created | fact.updated | ...
actor: {kind: user|agent, id: str}
target: {type: proposal|fact, id: str}
diff_before / diff_after: JSON
```

**Lifecycle**:
```
User/Agent → Proposal (pending)
    ↓ (auto-accept if confidence ≥ 0.85)
    ↓ (or manual approval)
Fact (active)
    ↓ (revoke/archive)
Fact (inactive)
    ↓ (reactivate)
Fact (active)
```

**Conflict Resolution**:
- Single-value keys (`preferred_name`) → **overwrite_latest**
- Multi-value keys (`favorite_tools[]`) → **keep_both**

---

### Layer 5: Infrastructure Layer

**Location**: Database, Settings, Docker, Web UI

**Components**:

#### Database (SQLite by default)
```
conversations          → Chat sessions
messages               → User/Assistant messages
runs                   → Async tasks (queued → running → succeeded/failed)
proposals              → Memory candidates
facts                  → Accepted memories
audit_events           → Immutable logs
settings               → Global config (key="v0", value=JSON)
sandbox_execs          → Code execution records
```

#### Settings (3-layer merge)
```
Final Config = Defaults ← Env ← DB
```

#### Docker
```
Runtime: Docker CLI (not Docker SDK)
Network: --network=none (Phase 1)
Security: --cap-drop=ALL --security-opt=no-new-privileges
```

#### Web Console (`apps/web-console/`)
```
React + TypeScript + Vite
API Proxy: /api/* → http://localhost:5173/*
```

---

## 🔄 DATA FLOW: How Information Moves

### Flow 1: User Chat → AI Response

```
┌─────────────────────────────────────────────────┐
│ User: "Remember I like matcha"                  │
└───────────────┬─────────────────────────────────┘
                ↓
┌───────────────────────────────────────────────────┐
│ Web Console / Connector                           │
│   POST /conversations/{id}/messages               │
│   body: {role: "user", content: "..."}            │
└───────────────┬───────────────────────────────────┘
                ↓
┌───────────────────────────────────────────────────┐
│ Core API (Orchestration Layer)                    │
│   1. Append MessageModel to DB                    │
│   2. Create RunModel (type="chat", status=queued) │
│   3. Inject settings_snapshot                     │
└───────────────┬───────────────────────────────────┘
                ↓
┌───────────────────────────────────────────────────┐
│ Agent Worker (Execution Layer)                    │
│   1. Poll: GET /runs/next (lease mechanism)       │
│   2. GET /memory/facts/active?conversation_id=... │
│   3. LLM.generate(messages + facts)               │
│   4. [Optional] POST /memory/proposals            │
│   5. PUT /runs/{id} {status: succeeded, output}   │
└───────────────┬───────────────────────────────────┘
                ↓
┌───────────────────────────────────────────────────┐
│ Core API → Web Console                            │
│   POST /conversations/{id}/messages               │
│   body: {role: "assistant", content: "..."}       │
└───────────────────────────────────────────────────┘
```

---

### Flow 2: Memory Proposal → Fact

```
┌─────────────────────────────────────────────────┐
│ Agent Worker detects memory-worthy info          │
│   confidence = 0.9 (above 0.85 threshold)        │
└───────────────┬─────────────────────────────────┘
                ↓
┌───────────────────────────────────────────────────┐
│ POST /memory/proposals                            │
│   payload: {key: "user.likes", value: "matcha"}   │
│   confidence: 0.9                                 │
│   scope_hint: "global"                            │
└───────────────┬───────────────────────────────────┘
                ↓
┌───────────────────────────────────────────────────┐
│ Core API (MemoryStore.create_proposal)            │
│   1. Create ProposalModel (status=pending)        │
│   2. Log audit_event (proposal.created)           │
│   3. Check AUTO_ACCEPT env var                    │
└───────────────┬───────────────────────────────────┘
                ↓
        ┌───────┴─────────┐
        │ confidence ≥ 0.85 │
        │ AUTO_ACCEPT = 1   │
        └───────┬───────────┘
                ↓ YES
┌───────────────────────────────────────────────────┐
│ Core API (MemoryStore.accept_proposal)            │
│   1. Check for conflicting Facts (same scope+key) │
│   2. Apply conflict resolution strategy           │
│      - overwrite_latest: Update existing Fact     │
│      - keep_both: Create new Fact (versioned)     │
│   3. Update ProposalModel.status = accepted       │
│   4. Log audit_event (proposal.accepted + fact.*) │
└───────────────────────────────────────────────────┘
```

---

### Flow 3: Skill Execution (Sandboxed Code)

```
┌─────────────────────────────────────────────────┐
│ Agent Worker decides to run Python code          │
│   tool_name: "skill.python.run"                  │
│   args: {code: "print('hello')"}                 │
└───────────────┬─────────────────────────────────┘
                ↓
┌───────────────────────────────────────────────────┐
│ ToolRuntime.invoke()                              │
│   → SkillsProvider.invoke()                       │
│      → POST /skills/python.run/invoke             │
└───────────────┬───────────────────────────────────┘
                ↓
┌───────────────────────────────────────────────────┐
│ Core API (app/api/skills.py)                      │
│   1. Read skills/python.run/manifest.json         │
│   2. Validate manifest schema                     │
│   3. Call POST /sandbox/execs                     │
└───────────────┬───────────────────────────────────┘
                ↓
┌───────────────────────────────────────────────────┐
│ Sandbox API (app/api/sandbox.py)                  │
│   1. Merge policies (System ← Settings ← Manifest)│
│   2. Create workspace dirs (inputs/work/artifacts)│
│   3. Write input files (normpath validation)      │
│   4. Path Adapter (Win → WSL if needed)           │
│   5. docker run --network=none --cap-drop=ALL ... │
│   6. Collect stdout/stderr (with truncation)      │
│   7. Write artifacts (manifest.json + meta.json)  │
│   8. Create SandboxExecRecord (DB audit)          │
└───────────────┬───────────────────────────────────┘
                ↓
┌───────────────────────────────────────────────────┐
│ Return to Agent Worker                            │
│   {exec_id, status, exit_code, artifacts_dir}     │
└───────────────────────────────────────────────────┘
```

---

## 🤖 AGENT LOOP: Single-Turn Execution

**Key File**: `packages/runtime/agent_loop.py`

**Flow**:
```
User Message
    ↓
1. TranscriptStore.append(user_event)
    ↓
2. LLM.generate(messages + facts) → Response
    ↓
    ├─ type=final → Return (no tool call)
    │
    └─ type=tool_call → Continue
            ↓
        3. ToolRunner.run(name, args, ctx)
            ├─ PolicyEngine.is_allowed() check
            ├─ ToolProvider.invoke()
            └─ TranscriptStore.append(tool_result)
            ↓
        4. LLM.generate(messages) → Final Response
            ↓
        5. MemoryHook.extract_candidates(transcript)
            ↓
        6. MemoryClient.propose(key, value, confidence)
```

**Current Limitation**:
- Only **1 tool call per turn** (single-shot)
- Phase 2 will add **multi-turn looping** (until LLM returns `type=final`)

---

## 💾 MEMORY MODEL: Proposal/Fact Lifecycle

### State Machine

```
Proposal States:
    pending ────┬──→ accepted ──→ (becomes Fact)
                ├──→ rejected
                └──→ expired (TTL timeout)

Fact States:
    active ──→ revoked ──→ [can reactivate]
           └─→ archived ──→ [can reactivate]
```

### Database Schema (Simplified)

#### proposals
```sql
id              INTEGER PRIMARY KEY
payload_key     TEXT NOT NULL
payload_value   JSON NOT NULL
status          TEXT CHECK(status IN ('pending', 'accepted', 'rejected', 'expired'))
confidence      REAL CHECK(confidence >= 0.0 AND confidence <= 1.0)
scope_hint      TEXT CHECK(scope_hint IN ('global', 'project', 'session'))
created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
```

#### facts
```sql
id              INTEGER PRIMARY KEY
key             TEXT NOT NULL
value           JSON NOT NULL
status          TEXT CHECK(status IN ('active', 'revoked', 'archived'))
scope           TEXT CHECK(scope IN ('global', 'project', 'session'))
project_id      TEXT
session_id      TEXT
version         INTEGER DEFAULT 1
created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP

-- Composite index for fast queries
INDEX idx_facts_scope_key_status ON facts(scope, key, status)
```

#### audit_events
```sql
id              INTEGER PRIMARY KEY
type            TEXT NOT NULL  -- proposal.created, fact.updated, etc.
actor_kind      TEXT NOT NULL  -- user | agent
actor_id        TEXT NOT NULL
target_type     TEXT NOT NULL  -- proposal | fact
target_id       TEXT NOT NULL
diff_before     JSON
diff_after      JSON
created_at      DATETIME DEFAULT CURRENT_TIMESTAMP

INDEX idx_audit_events_created ON audit_events(created_at DESC)
```

### Active Facts Injection

**When**: Before every LLM call
**How**:
```python
# Get active facts for current scope
facts = memory_client.list_facts(conversation_id=conv_id)
# Filter: scope=global OR session=conv_id, status=active

# Inject into system message
system_message += "\n\n## Active Facts\n"
for fact in facts:
    system_message += f"- {fact['key']}: {fact['value']}\n"
```

---

## ⚙️ EXECUTION MODEL: Tools & Skills

### Tool Catalog Architecture

**Multi-Provider System**:
```
ToolCatalog
    ├─ WebProvider (web.search, web.fetch)
    ├─ BuiltinProvider (stub implementations)
    ├─ MCPProvider_* (stdio MCP servers)
    ├─ SkillsProvider (skill.*)
    └─ StubProvider (testing)

Priority Order: ["web", "builtin", "mcp_*", "skills", "stub"]
```

**Tool Resolution**:
- Same tool name from multiple providers → first in priority order wins
- MCP tools prefixed with server name: `server_name.tool_name`
- Skills tools prefixed: `skill.python.run`

### Skill Manifest (Security Contract)

**Required Fields** (Phase 1):
```json
{
  "schema_version": "1.0",
  "id": "python.run",
  "runtime": {
    "kind": "docker",
    "image": "python:3.11-slim",
    "entrypoint": ["python"]
  },
  "interface": {
    "inputs": {...},  // JSON Schema
    "outputs": {...}
  },
  "permissions": {
    "fs": {
      "read": ["inputs/**", "work/**"],
      "write": ["work/**", "artifacts/**"]
    },
    "net": {"mode": "none"}  // MUST be "none" in Phase 1
  },
  "limits": {
    "timeout_ms": 30000,
    "memory_mb": 256,
    "cpu_cores": 1.0
  }
}
```

**Safety Invariants**:
- ✅ `runtime.kind` MUST be `docker`
- ✅ `permissions.net.mode` MUST be `none`
- ✅ `fs.read` ONLY `inputs/`, `work/`, `artifacts/`
- ✅ `fs.write` ONLY `work/`, `artifacts/`
- ❌ NO `--privileged` or `--cap-add`

---

## 🚫 FORBIDDEN ASSUMPTIONS (Critical!)

### ❌ DO NOT ASSUME:

1. **"Core API executes tools"**
   → FALSE. Core API only orchestrates. Agent Worker executes.

2. **"Facts are stored in a single table without scope"**
   → FALSE. Facts have `scope` field: global/project/session

3. **"Skills can access the network"**
   → FALSE. Phase 1 enforces `--network=none`

4. **"Proposals are automatically accepted"**
   → DEPENDS. Only if `confidence >= 0.85` AND `AUTO_ACCEPT=1`

5. **"Agent Loop supports multiple tool calls per turn"**
   → FALSE (currently). Only 1 tool call, then final response. Phase 2 adds loops.

6. **"LLM context window is unlimited"**
   → FALSE. MAX_MESSAGES=40 (hardcoded). Older messages dropped.

7. **"Memory conflicts are resolved by LLM"**
   → FALSE. Uses hardcoded strategies: overwrite_latest / keep_both

8. **"Skills can modify their own manifest"**
   → FALSE. Manifest is read-only at runtime.

9. **"WriteGate exists"**
   → FALSE (Phase 0). WriteGate is Phase 1 goal.

10. **"AI can directly modify code"**
    → FALSE. Must go through WriteGate (Phase 1+) with approval.

---

## 🔐 CRITICAL CONSTRAINTS (Enforce These!)

### Path Security
```yaml
# ALLOWED
- repo_root/**       (read-only)
- agent/**           (read-only, write via WriteGate)
- docs/**            (read-only, write via WriteGate)
- settings/**        (read via API, write via Settings API)
- workspace/**       (sandbox execution area)

# FORBIDDEN
- .git/**            (NEVER touch)
- .env               (contains secrets)
- node_modules/**    (managed by package manager)
- .venv*/**          (managed by Python)
```

### Database Constraints
```yaml
# MUST use MemoryStore methods, not raw SQL
- ✅ memory_store.create_proposal()
- ✅ memory_store.accept_proposal()
- ❌ session.execute("INSERT INTO proposals ...")

# Audit events are IMMUTABLE
- ✅ audit_logger.log_event()
- ❌ session.execute("UPDATE audit_events ...")
```

### Docker Constraints
```yaml
# REQUIRED flags (Phase 1)
--network=none
--cap-drop=ALL
--security-opt=no-new-privileges
--user=1000:1000

# FORBIDDEN flags
--privileged
--cap-add=*
--net=host
```

---

## 📚 Where to Find Things (Quick Reference)

### "Where is the Memory Proposal acceptance logic?"
→ `packages/memory/memory.py` → `MemoryStore.accept_proposal()`

### "How does Agent Loop call tools?"
→ `packages/runtime/agent_loop.py` → `AgentLoop.handle()`
→ `packages/runtime/tool_runner.py` → `ToolRunner.run()`

### "Where are Skills validated?"
→ `apps/core-api/app/services/skills/loader.py` (future)
→ Current: `apps/core-api/app/api/skills.py` → inline validation

### "How do Facts get injected into LLM context?"
→ `apps/agent-worker/worker/responder.py` → `_build_system_message()`

### "Where is the sandbox executor?"
→ `apps/core-api/app/api/sandbox.py` → `create_exec()`
→ `apps/core-api/app/services/sandbox/runner_docker.py` → `DockerRunner.run()`

### "How are Settings merged?"
→ `apps/core-api/app/api/settings.py` → `get_current_settings()`
→ Logic: `Defaults ← Env ← DB`

---

## 🔍 HOW TO QUERY (Active Commands for AI)

### When You Need to Find Code

**Question**: "Where is the code that handles X?"

**Method 1: Use Projection Tool** (Phase 0.2+)
```python
# Future tool (not yet implemented)
projection.query_implementation(
    feature="memory proposal acceptance",
    query_type="functions"  # or "files" or "classes"
)
→ Returns: [{file: "...", line: 123, snippet: "..."}]
```

**Method 2: Read Architecture Docs**
```
1. Check agent/architecture.md → "Where to Find Things"
2. Get module path (e.g., packages/memory/memory.py)
3. Use Read tool to examine code
```

**Method 3: Grep Codebase**
```python
# Search for specific patterns
Grep(pattern="accept_proposal", path="packages/memory")
Grep(pattern="class MemoryStore", path="packages")
```

---

### When You Need to Understand Data Flow

**Question**: "How does X flow through the system?"

**Answer Location**: `agent/architecture.md` → **DATA FLOW** section

Current flows documented:
- Flow 1: User Chat → AI Response
- Flow 2: Memory Proposal → Fact
- Flow 3: Skill Execution (Sandboxed Code)

**If flow not documented**: Trace from architecture layers
```
User action (Layer 5 UI)
  ↓ API call
Orchestration (Layer 2 core-api)
  ↓ Task delegation
Execution (Layer 3 agent-worker)
  ↓ State change
Memory (Layer 4)
  ↓ Audit
Infrastructure (Layer 5 DB)
```

---

### When You Need to Check Permissions

**Question**: "Can I do X?"

**Check Order**:
1. **Forbidden Paths** - `agent/policies/default.yaml` → `forbidden_paths`
   - If path in list → ABORT immediately
2. **Risk Level** - `agent/policies/default.yaml` → `risk_levels`
   - read_only (L0) → No approval needed
   - write (L1) → Approval required
   - execute (L2) → Approval + audit
   - destructive (L3) → Double confirmation
3. **Approval Required** - `agent/policies/default.yaml` → `approval_required`
   - Check if operation is in "always" list
4. **Frequency Limit** - `agent/policies/default.yaml` → `frequency_limits`
   - Check if action quota exceeded

**Example Check**:
```yaml
# Question: Can I modify apps/core-api/app/main.py?

# Step 1: Check forbidden_paths
- apps/**/*.py not in forbidden_paths ✓

# Step 2: Check read_only_paths
- apps/**/*.py in read_only_paths → NEED APPROVAL

# Step 3: Check risk_levels
- Operation: modify_code
- Risk: write (L1)
- approval_required: true

# Step 4: Check writegate_rules
- Triggers: path_matches: "apps/**/*.py" ✓
- Action: Generate ChangePlan → User approval → Apply

# Conclusion: Yes, but requires WriteGate flow
```

---

### When You Need to Propose Changes

**Question**: "How do I suggest a code modification?"

**Phase 0 (Current)**: Cannot modify code directly
```
Your response:
"I cannot modify code directly in Phase 0. However, I can:
1. Explain what should be changed
2. Generate a patch preview
3. Wait for Phase 1 WriteGate to be implemented
4. Or you can apply the change manually"
```

**Phase 1+ (WriteGate Available)**:
```python
# Step 1: Create ChangePlan
changePlan = {
    "objective": "Fix bug in memory acceptance logic",
    "affected_files": ["packages/memory/memory.py"],
    "risk_assessment": "LOW (bug fix in well-tested module)",
    "rollback_plan": "Git revert + restart services"
}

# Step 2: Generate ChangeSet (diff)
changeSet = {
    "file": "packages/memory/memory.py",
    "old_content": "...",
    "new_content": "...",
    "diff_unified": "..."
}

# Step 3: Request approval
POST /changesets
{plan: changePlan, changes: [changeSet]}

# Step 4: Wait for user approval
# Step 5: System applies atomically
# Step 6: Verify + record in audit
```

---

### When You Need Settings Info

**Question**: "What is the current configuration for X?"

**API**: `GET /settings`
```json
{
  "web": {
    "search": {
      "backend": "ddg_html",
      "timeout_ms": 15000
    },
    "providers": {
      "bocha": {"enabled": false, "api_key": "********"}
    }
  },
  "sandbox": {
    "runtime_mode": "auto",
    "workspace_root_win": "D:/workspace"
  }
}
```

**Note**: API keys are masked (******** shown instead of actual value)

**Settings Merge Logic**: `Defaults ← Env ← DB`

---

### When You Need Memory Context

**Question**: "What Facts are currently active?"

**API**: `GET /memory/facts/active?conversation_id=<id>`
```json
{
  "facts": [
    {
      "id": "123",
      "key": "user.preferred_name",
      "value": "Alice",
      "scope": "global",
      "status": "active"
    }
  ],
  "snapshot_id": "abc123..."  // Use for caching
}
```

**When to Query**:
- Before every LLM call (facts injected into system message)
- After accepting a Proposal (to verify it became a Fact)
- When user asks "What do you know about me?"

---

### When Stuck: Escalation Path

**Level 1: Check Cognition Layer**
```
1. Read agent/README.md (overview)
2. Check agent/architecture.md (structure)
3. Check agent/policies/default.yaml (constraints)
```

**Level 2: Check Source Code**
```
1. Use "Where to Find Things" section
2. Read actual implementation
3. Trace through data flow
```

**Level 3: Ask User**
```
If after checking docs + code, still unclear:
- Explain what you know
- Explain what's ambiguous
- Ask specific question (not "what should I do?")
```

**Example Good Question**:
> "I found two conflicting patterns:
> - `memory.py` uses `overwrite_latest` for single-value keys
> - But `key_policies` table allows custom strategies
>
> Should I trust `key_policies` table or hardcoded logic?
> (Affects how I handle conflict resolution)"

**Example Bad Question**:
> "How do I add a web provider?"
> (Should infer from architecture first)

---

## 🔮 Future Architecture (Phase 1-5 Preview)

### Phase 1: WriteGate
```
New Module: app/services/writegate.py
New Tables: change_plans, change_sets
New API: POST /changesets (propose), POST /changesets/{id}/approve
```

### Phase 2: Host Executor
```
New Module: worker/host_executor.py
New Permissions: read_file, write_file, apply_patch, run_tests
New API: POST /host/execute (with path whitelist)
```

### Phase 3: Reflection Loop
```
New Module: worker/reflection.py
New Memory Types: agent_capabilities, tool_reliability, known_limitations
New Cron: Periodic reflection job (analyze recent runs → propose improvements)
```

### Phase 4: SkillOps
```
New Tables: skill_registry, skill_health_checks
New API: POST /skills/install, POST /skills/{id}/update
Auto-doc: Generate agent/skills.md from usage logs
```

### Phase 5: Self-Modification Pipeline
```
Full Flow: Propose → Sandbox Validate → WriteGate → Host Executor → Health Check → Reflect
Safeguard: All changes require approval (no autonomous merge)
```

---

**Version**: 0.1.0
**Target Audience**: AI Agents (not human developers)
**Purpose**: Cognition Index (not implementation guide)
**Modification Protocol**: WriteGate Required (Phase 1+)
