# Protocol Package

## Purpose
Shared Pydantic schemas for events, tools, skills, MCP, and memory records.

## Must NOT do
- Include business logic.
- Execute side effects.
- Depend on external services.

## Integration points
- Core API request/response models.
- Runtime/worker payloads.
- Connector message formats.

## TODO
- Expand schema coverage for sessions and agents.
- Add JSON schema publishing tooling.
- Add versioned schema registry.
