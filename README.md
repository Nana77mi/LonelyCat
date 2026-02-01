# LonelyCat

“A lonely little cat lives in your computer. It doesn’t want to wreck the house—just wants to play with you.”

## Architecture

- **Python core**: FastAPI service (`apps/core-api`) and background worker (`apps/agent-worker`) for orchestration.
- **Node connectors**: integration bridges in `connectors/` (QQ OneBot v11, future WeChat).
- **Web console**: React/Vite UI shell in `apps/web-console`.
- **Shared packages**: protocol schemas, runtime, memory, KB, skills, MCP in `packages/`.

## Quickstart

```bash
make setup
```

Run all tests:

```bash
make test
```

Or run tests via pnpm + pytest:

```bash
pnpm test
python -m pytest
```

Run dev servers (examples):

```bash
# Core API
python -m uvicorn app.main:app --app-dir apps/core-api --reload

# Web console
pnpm --filter @lonelycat/web-console dev
```

## Security Note

LonelyCat defaults to **least privilege** access, sandboxed workspaces in `data/workspaces`, and audit-friendly design. Any tool execution or connector should enforce explicit allowlists and produce audit logs.
