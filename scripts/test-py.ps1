# Run Python tests (core-api + agent-worker). Equivalent to: make test-py
# Usage: from repo root, run: .\scripts\test-py.ps1
# Requires: .venv with deps (see .\scripts\setup.ps1); use core-api[test] for pytest.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $RepoRoot "packages"))) {
    Write-Error "Run from repo root or ensure scripts live in repo/scripts. Repo root: $RepoRoot"
}
Set-Location $RepoRoot

# Prefer Windows .venv (setup.ps1), fallback to WSL-style .venv-dev
$VenvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    $VenvPy = Join-Path $RepoRoot ".venv-dev\bin\python"
}
if (-not (Test-Path $VenvPy)) {
    Write-Error "No venv found. Run .\scripts\setup.ps1 first (creates .venv with test deps)."
}

$CORE_API_DIR = "apps\core-api"
$AGENT_WORKER_DIR = "apps\agent-worker"

# Path separator for PYTHONPATH (semicolon on Windows)
$sep = [System.IO.Path]::PathSeparator
$basePath = "packages$sep$CORE_API_DIR$sep$AGENT_WORKER_DIR"

Write-Host "Running core-api tests..."
$env:PYTHONPATH = "packages$sep$CORE_API_DIR$sep$AGENT_WORKER_DIR"
& $VenvPy -m pytest "$CORE_API_DIR/tests" -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "core-api tests failed (exit $LASTEXITCODE)."
    exit $LASTEXITCODE
}

Write-Host "Running agent-worker tests..."
$env:PYTHONPATH = "packages$sep$AGENT_WORKER_DIR"
& $VenvPy -m pytest "$AGENT_WORKER_DIR/tests" -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "agent-worker tests failed (exit $LASTEXITCODE)."
    exit $LASTEXITCODE
}

Write-Host "Python tests (core-api + agent-worker) done."
