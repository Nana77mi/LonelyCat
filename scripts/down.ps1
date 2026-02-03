# Stop core-api and agent-worker (processes started by up.ps1).
# Web console runs in foreground; stop it with Ctrl+C in that terminal.

$ErrorActionPreference = "SilentlyContinue"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PidDir = Join-Path $RepoRoot ".pids"
$ApiPidFile = Join-Path $PidDir "core-api.pid"
$WorkerPidFile = Join-Path $PidDir "agent-worker.pid"

Write-Host "Stopping LonelyCat services..."

foreach ($name, $path in @{ "core-api" = $ApiPidFile; "agent-worker" = $WorkerPidFile }) {
    if (-not (Test-Path $path)) {
        Write-Host "  No pid file for $name"
        continue
    }
    $pid = Get-Content $path
    if ($pid -match '^\d+$') {
        $p = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($p) {
            Stop-Process -Id $pid -Force
            Write-Host "  Stopped $name (pid=$pid)"
        } else {
            Write-Host "  $name not running (stale pid $pid)"
        }
    }
    Remove-Item $path -Force -ErrorAction SilentlyContinue
}

Write-Host "Done. If web-console was running in another terminal, stop it with Ctrl+C."
