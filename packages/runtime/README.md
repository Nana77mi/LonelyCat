# Runtime Package

## Purpose
Agent runtime scaffolding: loop, queues, tool runner, policy checks.

## Must NOT do
- Call LLMs directly in the runtime core.
- Hardcode connector endpoints.
- Execute tools without policy enforcement.

## Integration points
- `packages/protocol` for event and tool schemas.
- `apps/agent-worker` for execution.

## TODO
- Implement lane scheduling and concurrency.
- Add tool execution adapters.
- Integrate policy engine.
