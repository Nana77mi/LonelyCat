# MCP Package

## Purpose
Host and registry for Model Context Protocol (MCP) servers.

## Must NOT do
- Auto-connect to MCP servers without explicit configuration.
- Allow unsafe tools without permission checks.
- Persist secrets in manifests.

## Integration points
- Runtime policy checks.
- Core API configuration endpoints.

## TODO
- Implement MCP server discovery.
- Add permission policy storage.
- Build health monitoring.
