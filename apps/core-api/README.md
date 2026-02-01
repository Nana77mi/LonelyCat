# Core API

## Purpose
FastAPI service exposing REST and WebSocket endpoints for the LonelyCat control plane.

## Must NOT do
- Call LLM providers directly (delegate to runtime/worker).
- Execute tools without policy checks.
- Store secrets in code.

## Integration points
- `packages/protocol` for shared schemas.
- `packages/runtime` for agent loop and queue integration.
- `apps/agent-worker` for background execution.

## TODO
- Add authentication and authorization.
- Add request tracing and observability.
- Implement API routers for sessions and tools.
