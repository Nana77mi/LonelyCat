# Web Console

## Purpose
Minimal React control panel for configuring and monitoring the LonelyCat system.

## Must NOT do
- Store secrets in client-side code.
- Call internal services without authentication.
- Implement business logic (should live in API/worker).

## Integration points
- Core API endpoints for status and configuration.
- Future websocket events for live updates.

## TODO
- Add authentication flow.
- Build status dashboards.
- Implement settings management UI.
