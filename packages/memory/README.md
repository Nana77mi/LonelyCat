# Memory Package

## Purpose
Memory and knowledge storage abstractions (transcripts, facts, vectors).

This package implements the Memory Spec v0.1, providing:
- **Proposal/Fact lifecycle management**: Proposal → (Accept/Reject/Expire) → Fact → (Revoke/Archive/Reactivate)
- **Scope support**: global, project, and session-scoped facts
- **Conflict resolution**: Automatic handling of key collisions with configurable strategies
- **Audit logging**: Complete audit trail for all memory operations
- **SQLite persistence**: Database-backed storage with SQLAlchemy

## Architecture

### Core Components

- **`schemas.py`**: Pydantic models for Proposal, Fact, AuditEvent, and related enums
- **`db.py`**: SQLAlchemy database models and initialization
- **`facts.py`**: `MemoryStore` class implementing the core storage logic
- **`audit.py`**: `AuditLogger` class for recording audit events

### Data Model

The package uses a `key/value` model instead of the previous `subject/predicate/object` model:

- **Proposal**: Candidate memory items with `payload.key/value`, `scope_hint`, `source_ref`, etc.
- **Fact**: Accepted memory items with `key/value`, `scope`, `status`, `version`, etc.
- **AuditEvent**: Immutable records of all state changes

### Storage

- Uses SQLite by default (configurable via `LONELYCAT_MEMORY_DB_URL`)
- Database tables: `proposals`, `facts`, `audit_events`, `key_policies`
- Automatic table creation on first import

## Usage

### Basic Usage

```python
from memory.facts import MemoryStore
from memory.schemas import ProposalPayload, SourceRef, Scope, SourceKind

# Create a store instance
store = MemoryStore()

# Create a proposal
proposal = await store.create_proposal(
    payload=ProposalPayload(
        key="preferred_name",
        value="Alice",
        tags=[],
        ttl_seconds=None,
    ),
    source_ref=SourceRef(
        kind=SourceKind.MANUAL,
        ref_id="web-console",
        excerpt=None,
    ),
    confidence=0.9,
    scope_hint=Scope.GLOBAL,
)

# Accept the proposal
proposal, fact = await store.accept_proposal(
    proposal.id,
    scope=Scope.GLOBAL,
)

# List facts
facts = await store.list_facts(
    scope=Scope.GLOBAL,
    status=FactStatus.ACTIVE,
)

# Revoke a fact
await store.revoke_fact(fact.id)
```

### Conflict Resolution

When accepting a proposal with a key that already exists:

- **`overwrite_latest`**: Updates the existing fact and increments version
- **`keep_both`**: Creates a new fact with the same key

The strategy is determined by:
1. Explicit `strategy` parameter in `accept_proposal()`
2. Key policy configuration (in `key_policies` table)
3. Default heuristics based on key patterns

### Audit Logging

All operations automatically generate audit events:

```python
from memory.audit import AuditLogger

logger = AuditLogger()
events = logger.get_events(
    target_type="fact",
    target_id=fact.id,
    limit=10,
)
```

## API Integration

The package is designed to be used with FastAPI:

```python
from memory.db import get_db
from memory.facts import MemoryStore

@router.get("/facts")
async def list_facts(db = Depends(get_db)):
    store = MemoryStore(db=db)
    facts = await store.list_facts()
    return {"items": facts}
```

## Configuration

Environment variables:
- `LONELYCAT_MEMORY_DB_URL`: Database URL (default: `sqlite:///./lonelycat_memory.db`)
- `LONELYCAT_MEMORY_DB_ECHO`: Enable SQLAlchemy query logging (default: `false`)

## Must NOT do
- Persist sensitive data without encryption.
- Hardcode storage backends.
- Perform retrieval logic inside storage adapters.

## Integration points
- Agent runtime for recall and storage.
- KB ingestion pipeline.
- Core API for HTTP endpoints.

## TODO
- Add pluggable storage backends (PostgreSQL, etc.).
- Implement retention policies.
- Add encryption hooks.
- Add TTL-based automatic proposal expiration (background task).