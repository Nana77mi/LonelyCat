# Sandbox image (lonelycat-sandbox:py312)

See [docs/spec/sandbox.md](../../docs/spec/sandbox.md).

## Build

From repo root:

- **Windows (PowerShell):** `.\scripts\build_sandbox_image.ps1`
- **WSL / Linux:** `./scripts/build_sandbox_image.sh`

Requires Docker Desktop (Windows) or Docker (WSL2/Linux) to be running.

## Verify

Default ENTRYPOINT is `bash`. Use `--entrypoint python` for Python one-liners:

```bash
docker run --rm --entrypoint python lonelycat-sandbox:py312 -c "print(1)"
# Expected: 1

docker run --rm lonelycat-sandbox:py312 -c "echo hello"
# Expected: hello (bash -c "echo hello")
```

## Image

- Base: `python:3.12-slim`
- User: `sandbox` (uid 1000)
- Installed: bash, coreutils, findutils, jq, git
- Workspace: `/workspace/inputs` (ro), `/workspace/work` (rw), `/workspace/artifacts` (rw)
- Default WORKDIR: `/workspace/work`, ENTRYPOINT: `bash`
