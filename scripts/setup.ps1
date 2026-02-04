# LonelyCat setup for Windows PowerShell.
# Creates venv, installs Python packages (packages/* + agent-worker) and web-console deps.
# Run from repo root: .\scripts\setup.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $RepoRoot "packages"))) {
    Write-Error "Run this script from repo root or ensure scripts live in repo/scripts. Repo root used: $RepoRoot"
}
Set-Location $RepoRoot

$Venv = Join-Path $RepoRoot ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$Pip = Join-Path $Venv "Scripts\pip.exe"

# Python venv
if (-not (Test-Path $Py)) {
    Write-Host "Creating virtual environment at $Venv ..."
    python -m venv $Venv
}
Write-Host "Upgrading pip and installing setuptools, wheel..."
& $Py -m pip install --upgrade pip
& $Pip install setuptools wheel

# Monorepo packages (match Makefile setup-py)
$packages = @(
    "packages\memory",
    "packages\runtime",
    "packages\mcp",
    "packages\protocol",
    "packages\kb"
)
foreach ($p in $packages) {
    $pyproject = Join-Path $RepoRoot ($p + "\pyproject.toml")
    if (Test-Path $pyproject) {
        Write-Host "Installing $p ..."
        & $Pip install -e (Join-Path $RepoRoot $p)
    }
}

# Core API
$apiPyproject = Join-Path $RepoRoot "apps\core-api\pyproject.toml"
if (Test-Path $apiPyproject) {
    Write-Host "Installing core-api ..."
    & $Pip install -e "apps/core-api"
}

# Agent worker
$awPyproject = Join-Path $RepoRoot "apps\agent-worker\pyproject.toml"
if (Test-Path $awPyproject) {
    Write-Host "Installing agent-worker ..."
    & $Pip install --no-build-isolation -e "apps/agent-worker[test]"
}

# Web console (requires Node.js and pnpm)
$webDir = Join-Path $RepoRoot "apps\web-console"
if (Test-Path (Join-Path $webDir "package.json")) {
    # Ensure pnpm is available (corepack or global install)
    if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
        Write-Host "pnpm not found. Enabling corepack or installing via npm..."
        corepack enable 2>$null
        if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
            npm install -g pnpm
        }
    }
    Write-Host "Installing web-console dependencies (pnpm)..."
    Push-Location $webDir
    try {
        pnpm install --no-frozen-lockfile
    } finally {
        Pop-Location
    }
}

# Pid directory for up/down
$PidDir = Join-Path $RepoRoot ".pids"
if (-not (Test-Path $PidDir)) {
    New-Item -ItemType Directory -Path $PidDir | Out-Null
    Write-Host "Created $PidDir"
}

Write-Host "Setup complete. Run .\scripts\up.ps1 to start services."
