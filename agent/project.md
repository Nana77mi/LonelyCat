---
# Machine-Readable Metadata (YAML Frontmatter)
project_name: "LonelyCat"
tagline: "Self-Evolving Local AgentOS"
version: "0.2.0-alpha"
status: "active_development"
phase: "Phase 0 - Cognitive Layer"
repository: "https://github.com/Nana77mi/LonelyCat"

# AI Agent Metadata (Critical for self-modification)
ai_role: "cognition_source"
write_access: "restricted"
modification_protocol: "writegate_required"

# Core Objectives
objectives:
  primary: "Build a local-first AI agent platform that can understand, modify, and evolve itself"
  secondary:
    - "Multi-endpoint integration (CLI, Web, QQ, WeChat)"
    - "Safe and auditable autonomous operations"
    - "Long-term memory and self-reflection capabilities"
    - "Extensible skill/tool ecosystem"

# Current Capabilities
capabilities:
  conversation: true
  memory_lifecycle: true  # Proposal → Fact → Audit
  skills_sandbox: true    # Docker-based execution
  mcp_integration: true   # MCP protocol support
  web_tools: true         # Search & Fetch
  self_modification: false  # Phase 1+ goal

# Technology Stack
tech_stack:
  backend: ["Python 3.11+", "FastAPI", "SQLAlchemy"]
  frontend: ["React", "TypeScript", "Vite"]
  database: ["SQLite", "Postgres (optional)"]
  execution: ["Docker"]
  connectors: ["Node.js", "OneBot v11"]

# Key Constraints
constraints:
  platform: "Windows / Linux / WSL / macOS"
  llm_providers: ["OpenAI", "Qwen", "Ollama", "DeepSeek", "Stub"]
  network_isolation: "Skills run with --network=none by default"
  memory_scope: ["global", "project", "session"]

---

# LonelyCat Project Overview

> **"A lonely little cat lives in your computer. It doesn't want to wreck the house—just wants to play with you."**

LonelyCat is not just a chatbot. It's an evolving **Local AgentOS** that aims to:
- **Understand** its own codebase
- **Propose** improvements to itself
- **Execute** changes safely with human oversight
- **Remember** past interactions and lessons learned

---

## 🎯 Project Vision

### The Ultimate Goal

Create an AI system that can:

1. **Cognition** - Read and comprehend its own source code
2. **Proposal** - Suggest architectural improvements and bug fixes
3. **Execution** - Apply approved changes through secure mechanisms
4. **Reflection** - Learn from outcomes and update its own knowledge base

### Why "Self-Evolving"?

Traditional AI agents are **tools** - they execute commands but don't improve their own tools.

LonelyCat is different:
- **Phase 0** - AI reads `agent/` directory to understand project structure
- **Phase 1** - AI proposes code changes through WriteGate approval system
- **Phase 2** - AI can safely modify local files within security boundaries
- **Phase 3** - AI reflects on past runs and proposes systemic improvements
- **Phase 4** - AI manages its own skill catalog and dependencies
- **Phase 5** - AI can autonomously evolve (with guardrails)

---

## 🏗️ Architecture Overview (High-Level)

LonelyCat uses a **5-layer architecture**:

```
┌─────────────────────────────────────────────────┐
│        [ Cognitive Layer ]                      │  ← agent/ directory (you are here)
│   AI reads project structure, policies,         │
│   architecture docs to understand itself        │
└─────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────┐
│     [ Orchestration Layer ]                     │  ← apps/core-api
│   Agent Loop, Planner, WriteGate                │
│   (Decides WHAT to do, enforces policies)       │
└─────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────┐
│      [ Execution Layer ]                        │  ← apps/agent-worker + sandbox
│   Skills, Host Executor, Tool Runtime           │
│   (Does the actual work, sandboxed)             │
└─────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────┐
│       [ Memory Layer ]                          │  ← packages/memory
│   Proposal → Fact → Reflection                  │
│   (Long-term knowledge, audited)                │
└─────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────┐
│     [ Infrastructure Layer ]                    │  ← Settings, DB, Logs, UI
│   FastAPI, SQLite, Docker, Web Console          │
└─────────────────────────────────────────────────┘
```

See [architecture.md](./architecture.md) for detailed explanation.

---

## 📦 Repository Structure

```
LonelyCat/
│
├── agent/                   ← AI Cognitive Source (Phase 0)
│   ├── project.md           ← This file
│   ├── architecture.md      ← System design
│   ├── policies/            ← Safety constraints
│   └── workflows/           ← Task procedures
│
├── apps/                    ← Main applications
│   ├── core-api/            ← FastAPI orchestration service
│   ├── agent-worker/        ← Background LLM execution
│   └── web-console/         ← React UI
│
├── packages/                ← Shared libraries
│   ├── memory/              ← Memory/Facts/Audit system
│   ├── runtime/             ← Agent Loop runtime
│   ├── protocol/            ← Shared schemas
│   ├── mcp/                 ← MCP protocol support
│   ├── kb/                  ← Knowledge base (embeddings)
│   └── skills/              ← Skills framework (Phase 4)
│
├── connectors/              ← Integration bridges
│   ├── qq-onebot-bridge/    ← QQ bot connector
│   └── wechat-bridge/       ← (planned)
│
├── skills/                  ← Skill definitions
│   ├── shell.run/           ← Shell script executor
│   ├── python.run/          ← Python code executor
│   └── _schema/             ← Manifest schema
│
├── docs/                    ← Technical documentation
│   ├── spec/                ← API specs
│   └── websearch/           ← Web provider docs
│
└── scripts/                 ← Utility scripts
    ├── setup.ps1            ← Windows setup
    ├── test-py.ps1          ← Windows tests
    └── ...
```

---

## 🔄 Development Phases

### ✅ Completed (Pre-Phase 0)

- [x] **Basic Agent Loop** - User → LLM → Tool → Response
- [x] **Memory System** - Proposal/Fact lifecycle + Audit logs
- [x] **Skills Sandbox** - Docker-based code execution
- [x] **Web Tools** - Search (DDG, Baidu, Searxng, Bocha) + Fetch (cache + artifacts)
- [x] **MCP Integration** - External tool protocol support
- [x] **Multi-LLM** - OpenAI, Qwen, Ollama, DeepSeek
- [x] **Web Console** - Memory management UI
- [x] **QQ Connector** - OneBot v11 integration

### 🚧 Phase 0 - Cognitive Layer (Current)

**Goal**: AI can understand its own codebase

**Tasks**:
1. [x] Deep architecture analysis
2. [x] Create `agent/` directory
3. [ ] Document project goals (`project.md` - this file)
4. [ ] Document architecture (`architecture.md`)
5. [ ] Define operational policies (`policies/`)
6. [ ] Create workflow examples (`workflows/`)
7. [ ] Build projection tool (generate `AGENTS.md`, `CLAUDE.md`)

**Success Criteria**:
- AI can answer "Where is the Memory Proposal acceptance logic?"
- AI can explain "How does the Agent Loop work?"
- AI knows "What files should never be modified?"

### 📋 Phase 1 - WriteGate (Next)

**Goal**: AI can safely propose code changes

**Key Components**:
- **ChangePlan** - Structured description of intended modifications
- **ChangeSet** - Concrete diffs with risk assessment
- **Approval UI** - Human reviews proposed changes
- **ChangeSet DB** - Audit trail of all modifications
- **Rollback** - Undo mechanism for failed changes

**Workflow**:
```
AI analyzes issue
  ↓
AI creates ChangePlan
  ↓
User reviews plan (reject/approve)
  ↓
AI generates ChangeSet (diff)
  ↓
User reviews diff (reject/approve)
  ↓
System applies changes
  ↓
System runs verification (tests)
  ↓
Record in audit log
```

### 📋 Phase 2 - Host Executor

**Goal**: AI can execute local operations safely

**Capabilities**:
- Read files (whitelisted paths)
- Write files (with approval)
- Apply patches (with rollback)
- Run tests (sandboxed)
- Restart services (core-api, agent-worker)

**Security**:
- Path whitelist (`repo_root/**`, `agent/**`, `docs/**`, `settings/**`)
- Operation audit log (what/when/who/result)
- Rollback for destructive operations

### 📋 Phase 3 - Memory Upgrade

**Goal**: AI learns from experience

**New Capabilities**:
- **Reflection Loop** - Periodic analysis of recent runs/errors/feedback
- **Agent Self-Model** - AI knows its own capabilities/limitations
- **Memory Types**:
  - `agent_capabilities[]` - What AI has successfully done
  - `tool_reliability[]` - Which tools are dependable
  - `known_limitations[]` - What AI struggles with

**Example Reflection**:
```
Observed: 3 failed attempts to parse complex JSON
Analysis: llama2 model lacks robust JSON parsing
Proposal: Add retry logic with schema validation
Confidence: 0.9
```

### 📋 Phase 4 - SkillOps

**Goal**: AI manages its own skill catalog

**Features**:
- **Skill Registry** - DB table tracking skill versions/health
- **Auto-documentation** - Generate skill usage guides from logs
- **Health checks** - Periodic skill execution validation
- **Dependency management** - Install/update skill dependencies

**Workflow**:
```
AI detects need for new capability
  ↓
AI searches skill marketplace (future)
  ↓
AI proposes skill installation
  ↓
User approves
  ↓
AI installs + validates skill
  ↓
AI updates skill catalog
```

### 📋 Phase 5 - Self-Modification Pipeline

**Goal**: Controlled autonomous evolution

**Full Flow**:
```
1. AI proposes architectural improvement
2. Sandbox validation (run tests, check types)
3. WriteGate approval (human review)
4. Host Executor applies change
5. Health check (service restart, integration tests)
6. Reflection loop (record outcome, lessons learned)
```

**Safeguards**:
- All changes require human approval (no autonomous merge)
- Changes are atomic (all-or-nothing)
- Automatic rollback on failure
- Comprehensive audit trail

---

## 🎮 Current User Experience

### CLI Chat
```bash
$ python -m agent_worker.chat "Remember that I like matcha"
Assistant: I'll remember that! [Proposal created]
```

### Web Console
1. Open `http://localhost:8000`
2. View/accept Memory Proposals
3. Browse Active Facts
4. Monitor conversation history

### QQ Bot
```
User: @LonelyCat 今天天气怎么样？
Bot: [Calls web.search tool] 今天北京晴，15-25°C
```

---

## 🎮 Target Experience (After Phase 5)

### AI Self-Improvement
```
User: "The memory conflict resolution is too simplistic"

AI: I agree. I analyzed 50 recent conflicts and found:
    - 30% could be merged intelligently
    - 20% needed LLM-driven resolution

    I propose:
    1. Add vector similarity check for near-duplicates
    2. Use LLM to generate merge suggestions
    3. Show comparison UI in Web Console

    Estimated effort: 4 hours
    Risk level: LOW (only affects memory module)

    [ChangePlan attached]
    Approve? [Y/n]
```

---

## 🛡️ Core Principles

### 1. **Local-First**
- No cloud dependency (except LLM API)
- All data stored locally (SQLite by default)
- Works offline (with local LLM like Ollama)

### 2. **Safety by Design**
- All modifications require approval (no autonomous destructive actions)
- Sandbox isolation (Skills run in Docker with `--network=none`)
- Audit everything (immutable logs of all state changes)

### 3. **Extensibility**
- MCP protocol for external tools
- Skills framework for custom logic
- Multi-LLM support (easy to add new providers)

### 4. **Transparency**
- AI explains its reasoning (Memory Proposals include confidence scores)
- Diffs shown before applying (ChangeSets are human-readable)
- Audit trail queryable (every Fact change logged)

---

## 🔧 Key Technologies

### Backend
- **FastAPI** - Modern async web framework
- **SQLAlchemy** - ORM with SQLite/Postgres support
- **Pydantic** - Data validation and serialization

### Frontend
- **React** - UI library
- **TypeScript** - Type-safe JavaScript
- **Vite** - Fast build tool

### Execution
- **Docker** - Skill sandboxing
- **subprocess** - Local command execution

### Memory
- **SQLite** - Default database (easy setup)
- **Postgres** - Optional (for production)

### LLM Providers
- **OpenAI** - GPT-4, GPT-3.5
- **Qwen** - Alibaba Cloud
- **Ollama** - Local models (llama2, mistral, etc.)
- **DeepSeek** - DeepSeek Coder
- **Stub** - Testing

---

## 🚀 Getting Started (For Developers)

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker (for skills)
- pnpm (for frontend)

### Quick Setup

**Windows (PowerShell)**:
```powershell
.\scripts\setup.ps1
.\scripts\up.ps1
```

**Linux / macOS**:
```bash
make setup
make up
```

**Access**:
- Web Console: http://localhost:8000
- API Docs: http://localhost:5173/docs

### Running Tests

**Windows**:
```powershell
.\scripts\test-py.ps1
```

**Linux / macOS**:
```bash
make test-py
```

---

## 🤝 Contributing

### For Human Developers

1. **Read this doc** - Understand project vision
2. **Check [architecture.md](./architecture.md)** - Learn system design
3. **Review [policies/](./policies/)** - Know the constraints
4. **Follow workflows** - See [workflows/](./workflows/) for common tasks

### For AI Agents

1. **Query projections** - Find relevant code
2. **Propose changes** - Use Memory Proposal system
3. **Explain reasoning** - Include confidence scores
4. **Respect policies** - Never bypass WriteGate

---

## 📚 Further Reading

- [architecture.md](./architecture.md) - Detailed system design
- [policies/default.yaml](./policies/default.yaml) - Core safety rules
- [workflows/](./workflows/) - Task-specific guides
- [Main README](../README.md) - User-facing documentation
- [docs/spec/](../docs/spec/) - API specifications

---

## 🔮 Long-Term Vision (2-3 Years)

### Autonomous Research Assistant
```
User: "Implement OAuth2 for our API"

AI: I'll research OAuth2 best practices, analyze our current auth system,
    propose an implementation plan, generate code, write tests, update docs,
    and submit a PR for your review. Estimated time: 6 hours.

    [Starts working autonomously, updates you on progress]
```

### Self-Healing System
```
[Agent detects error spike in logs]

AI: I noticed 50 errors in the last hour related to memory conflict resolution.
    Root cause: Two agents modifying same Fact simultaneously.

    I propose adding a lock mechanism. Here's a patch:
    [Diff shown]

    This fix will prevent 95% of these errors (based on simulation).
    Apply? [Y/n]
```

### Knowledge Accumulation
```
After 6 months of operation:

AI: Based on 1000+ conversations, I've identified these patterns:
    - Users prefer concise responses (avg length: 200 words)
    - Tool failures often due to timeout (increase default to 30s)
    - Memory Proposals above 0.9 confidence are 98% accepted

    I recommend updating default settings and retraining my response model.
    [Detailed analysis attached]
```

---

**Version**: 0.1.0
**Author**: LonelyCat Core Team
**Last Updated**: 2026-02-09
**Status**: Phase 0 - Building AI Cognition
