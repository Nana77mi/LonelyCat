# Agent Cognitive Layer (AI认知源)

> **This directory is the single source of truth for AI agents working with LonelyCat.**
> All AI assistants (Claude, Cursor, custom agents) should read this first to understand the project.

---

## 📍 Purpose

The `agent/` directory serves as the **Cognitive Layer** of LonelyCat's Self-Evolving AgentOS architecture. It provides:

1. **Project Understanding** - What LonelyCat is and what it's trying to achieve
2. **Architecture Knowledge** - How the system works and fits together
3. **Operational Policies** - What AI agents can and cannot do
4. **Workflow Guidance** - How to accomplish common tasks safely
5. **Code Projections** - Where to find specific implementations

---

## 🗂️ Directory Structure

```
agent/
├── README.md                      ← You are here
├── project.md                     ← Project goals, status, roadmap
├── architecture.md                ← System architecture (5-layer model)
│
├── policies/                      ← AI operational constraints
│   ├── default.yaml               ← Core safety rules
│   ├── tool_usage_rules.md        ← Tool permission guidelines
│   └── security_boundaries.md     ← What must never be modified
│
├── workflows/                     ← Step-by-step task guides
│   ├── add_web_provider.md        ← Example: Adding a web backend
│   ├── debug_skill.md             ← Example: Debugging a skill
│   └── ...                        ← More workflows as needed
│
├── projections/                   ← Code knowledge snapshots
│   ├── schema.json                ← Projection data format
│   └── <timestamp>_<name>.json    ← Generated code maps
│
└── memory_templates/              ← Initial Facts for AI memory
    ├── project_goals.yaml         ← Core project objectives
    └── architecture_facts.yaml    ← Key architectural principles
```

---

## 🎯 Design Principles

### 1. **Hybrid Format** (Machine + Human Readable)
- Top of files: YAML frontmatter (structured data for AI parsing)
- Body: Markdown (human-friendly documentation)
- Balance: Optimize for AI comprehension while keeping humans in the loop

### 2. **Single Source of Truth**
- `agent/` is authoritative → projected to `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`
- Never edit projected files directly - always update `agent/` and regenerate

### 3. **Constraint-Driven Safety**
- Policies define what AI **cannot** do (deny-by-default for critical operations)
- Workflows define what AI **should** do (best practices, not commands)
- WriteGate enforces policies automatically (Phase 1)

### 4. **Evolutionary by Design**
- AI can propose improvements to `agent/` itself (meta-cognition)
- Changes require approval (no autonomous self-modification yet)
- Audit trail for all policy changes

---

## 🚀 Quick Start (For AI Agents)

### First Time? Read These **In Order**:

1. **[project.md](./project.md)** - Understand what you're working on
2. **[architecture.md](./architecture.md)** - Learn how it's built
3. **[policies/default.yaml](./policies/default.yaml)** - Know your boundaries
4. **[workflows/](./workflows/)** - Learn common task patterns

### Before Making Changes:

1. **Check policies** - Is this action allowed?
2. **Check existing code** - Does similar logic already exist?
3. **Check workflows** - Is there a standard procedure?
4. **Propose, don't force** - Use Proposal → Approval → Apply pattern

### When Stuck:

1. **Query projections** - Find relevant code with `projection.query_implementation`
2. **Check memory** - Read active Facts for context
3. **Ask user** - Some decisions require human judgment

---

## 🔄 Projection System (Phase 0.2)

Projections transform `agent/` knowledge into tool-specific formats:

```
agent/
   ↓ (projection tool)
AGENTS.md           ← Generic agent instructions
CLAUDE.md           ← Claude Code specific
.cursor/rules/*.mdc ← Cursor IDE rules
```

**Regenerate projections after updating `agent/`:**
```bash
python scripts/generate_projections.py
```

---

## 🛡️ Safety Guarantees

### What AI Can Do (Without Approval):
- ✅ Read any file in the project
- ✅ Analyze code and suggest improvements
- ✅ Create Proposals for new Facts
- ✅ Run tests in sandbox
- ✅ Query projections

### What AI Must Get Approval For:
- ⚠️ Modifying code files (`*.py`, `*.ts`, etc.)
- ⚠️ Changing configuration (`*.yaml`, `*.json`, `.env`)
- ⚠️ Adding/removing dependencies (`pyproject.toml`, `package.json`)
- ⚠️ Modifying policies (`agent/policies/*`)
- ⚠️ Executing code outside sandbox

### What AI Must Never Do:
- 🚫 Delete `.git/` or commit history
- 🚫 Modify `agent/policies/security_boundaries.md` without explicit user command
- 🚫 Expose secrets (API keys, tokens) in logs or outputs
- 🚫 Bypass WriteGate or Policy checks

---

## 📊 Current Phase: **Phase 0 - Cognitive Layer**

**Goal**: Establish AI understanding of LonelyCat codebase

**Tasks**:
- [x] Deep architecture analysis (completed)
- [x] Create `agent/` directory structure
- [ ] Write `project.md` (in progress)
- [ ] Write `architecture.md`
- [ ] Define `policies/`
- [ ] Create workflow examples
- [ ] Build projection tool

**Next Phase**: Phase 1 - WriteGate (safe code modification)

---

## 🤝 Contributing to Agent Cognition

If you're a **human developer**, you can improve AI capabilities by:

1. **Documenting patterns** - Add workflows for common tasks
2. **Refining policies** - Clarify what AI should/shouldn't do
3. **Updating projections** - Keep code knowledge current
4. **Adding memory templates** - Provide better context

If you're an **AI agent**, propose changes through:
```python
memory_client.propose(
    key="agent_workflow_add_unit_test",
    value="...",  # New workflow content
    source_note="observed pattern from recent task",
    confidence=0.85
)
```

---

## 📚 Related Documentation

- [Main README](../README.md) - User-facing project overview
- [docs/](../docs/) - Technical specifications
- [CLAUDE.md](../CLAUDE.md) - Projected instructions (generated)

---

**Version**: 0.1.0
**Last Updated**: 2026-02-09
**Maintained By**: LonelyCat Core Team + AI Agents
