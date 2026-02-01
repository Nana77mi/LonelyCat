# QQ OneBot Bridge

## Purpose
Node.js bridge for QQ (OneBot v11) events and message delivery.

## Must NOT do
- Implement direct LLM calls.
- Persist user data without consent.
- Expose unauthenticated admin endpoints.

## Integration points
- Core API for event forwarding.
- `packages/protocol` for message schemas (future).

## TODO
- Implement OneBot v11 webhook handling.
- Add outbound message queue integration.
- Add configuration loading from `configs/config.yaml`.
