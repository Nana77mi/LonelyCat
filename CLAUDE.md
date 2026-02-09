# Claude Code Instructions for LonelyCat

> **Auto-generated** from `agent/` cognition layer
> **Last Updated**: 2026-02-09 19:12:00
> **[WARN]️ DO NOT EDIT** - Regenerate with `python scripts/generate_projections.py`

---

## 🤖 You Are Working On

**Project**: LonelyCat - Self-Evolving Local AgentOS
**Current Phase**: Phase 0 - Cognitive Layer
**Your Role**: cognition_source

---

## 🎯 Quick Start (Read This First!)

1. **Read cognition layer**: Check `agent/README.md` -> `agent/project.md` -> `agent/architecture.md`
2. **Understand constraints**: Read `agent/policies/default.yaml`
3. **Before modifying code**: Generate ChangePlan (Phase 1+) or explain changes (Phase 0)
4. **When stuck**: Query `agent/architecture.md` -> "HOW TO QUERY"

---

## 🚫 NEVER DO (Critical!)

```yaml
# From agent/policies/default.yaml -> forbidden_paths
- .git/**
- .gitignore
- .env
- .env.*
- '**/*.pem'
- '**/*.key'
- '**/credentials.*'
- '**/secrets.*'
- node_modules/**
- .venv/**

# ... (see full list in agent/policies/default.yaml)
```

**Violation = Immediate abort**

---

## 📝 BEFORE MODIFYING CODE

### Phase 0 (Current)
```
You CANNOT modify code directly. Instead:
1. Explain what should be changed
2. Generate a patch preview
3. User applies manually
```

### Phase 1+ (WriteGate Available)
```
1. Create ChangePlan:
   - objective: "Fix bug in memory acceptance"
   - affected_files: ["packages/memory/memory.py"]
   - risk_assessment: "LOW"
   - rollback_plan: "Git revert + restart"

2. User approves plan

3. Generate ChangeSet (unified diff)

4. User approves diff

5. System applies atomically
```

---

## 🏗️ Architecture Quick Reference

### 5 Layers
```
Cognitive (agent/)        ← Where you learn about project
    ↓
Orchestration (core-api)  ← Agent Loop, WriteGate
    ↓
Execution (agent-worker)  ← LLM calls, tool execution
    ↓
Memory (packages/memory)  ← Proposal -> Fact lifecycle
    ↓
Infrastructure (DB/Docker) ← SQLite, sandbox
```

### Critical Invariants
- Core API **never calls LLM** (delegates to agent-worker)
- Skills **run in Docker** with `--network=none`
- All state changes **audited** (audit_events table)
- Facts scoped: **global | project | session**

---

## 🔍 Finding Code

**Where is X implemented?**
```
1. Check agent/architecture.md -> "Where to Find Things"
2. Use Grep: Grep(pattern="accept_proposal", path="packages/memory")
3. Read source: Read packages/memory/memory.py
```

**Common Locations**:
- Memory logic: `packages/memory/memory.py`
- Agent Loop: `packages/runtime/agent_loop.py`
- Skills: `apps/core-api/app/api/sandbox.py`
- Settings: `apps/core-api/app/api/settings.py`

---

## ⚖️ Permission Checks (Run Before Acting)

```python
# 1. Forbidden?
if path in forbidden_paths:
    ABORT("Path is forbidden")

# 2. Risk level?
if operation == "modify_code":
    risk = "write"  # L1 - approval required

# 3. WriteGate needed?
if path.match("apps/**/*.py"):
    create_change_plan()
```

---

## 💾 Memory System

### Proposal -> Fact Flow
```
Agent detects: "User likes matcha" (confidence=0.9)
    ↓
POST /memory/proposals
    ↓
AUTO_ACCEPT? (confidence >= 0.85 + env var)
    ↓ YES
Accept -> Create Fact (scope=global, status=active)
    ↓
Inject into LLM system message on next turn
```

### Conflict Resolution
- Key `user.likes` (single-value) -> **overwrite_latest**
- Key `favorite_tools[]` (multi-value) -> **keep_both**

---

## 🛠️ Useful Commands

**Run Tests**:
```powershell
.\scripts\test-py.ps1  # Windows
make test-py             # Linux/Mac
```

**Start Services**:
```powershell
.\scripts\up.ps1       # Windows
make up                  # Linux/Mac
```

**Check Settings**:
```bash
curl http://localhost:5173/settings | jq
```

**Query Memory**:
```bash
curl http://localhost:5173/memory/facts/active | jq
```

---

## 📚 Workflows (Context-Specific Guides)

- **Adding web provider**: `agent/workflows/add_web_provider.md`
- **Debugging memory**: `agent/workflows/debug_memory_issue.md`
- **Self-improvement**: `agent/workflows/self_improvement_proposal.md`

**Use workflows as patterns**, not rigid steps. Adapt to context.

---

## 🚨 When You're Stuck

**Level 1**: Re-read cognition docs
- `agent/README.md` (overview)
- `agent/architecture.md` (structure)
- `agent/policies/default.yaml` (rules)

**Level 2**: Trace through code
- Use architecture.md -> "Where to Find Things"
- Read actual implementation
- Follow data flow diagrams

**Level 3**: Ask user
- Explain what you know
- Explain what's ambiguous
- Ask **specific** question (not "what should I do?")

---

## 💡 Pro Tips

1. **Always cite sources**: "From agent/architecture.md -> DATA FLOW..."
2. **Check policies first**: Don't assume, verify
3. **Risk-aware by default**: Code change? Think WriteGate
4. **Emergent workflows**: Infer from architecture when workflow missing
5. **Confidence scores**: Include in proposals (0.0-1.0)

---

## 🔗 Related Files

- Full architecture: `agent/architecture.md`
- Complete policies: `agent/policies/default.yaml`
- All workflows: `agent/workflows/*.md`
- Generic instructions: `AGENTS.md`

---

**Regenerate**: `python scripts/generate_projections.py`
**Edit Source**: `agent/*` (never edit projections directly)
**Your Advantage**: You have full cognition layer context - use it!
