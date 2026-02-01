# Agent Worker

## Purpose
Background worker responsible for executing tasks, tools, and long-running jobs.

## Must NOT do
- Expose public HTTP endpoints.
- Access external APIs without policy enforcement.
- Persist secrets to disk.

## Integration points
- `packages/runtime` for agent loop and tool execution.
- `packages/memory` for transcript and fact storage.

## TODO
- Add queue backend integration (Redis, RabbitMQ).
- Implement task retries and dead-letter handling.
- Add structured logging and metrics.
