# Stop core-api and agent-worker (processes started by up.ps1).
# Web console runs in foreground; stop it with Ctrl+C in that terminal.
# Uses taskkill to avoid blocking; removes pid files after.

$ErrorActionPreference = "SilentlyContinue"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PidDir = Join-Path $RepoRoot ".pids"
$ApiPidFile = Join-Path $PidDir "core-api.pid"
$WorkerPidFile = Join-Path $PidDir "agent-worker.pid"

Write-Host "Stopping LonelyCat services..."

$services = @{
    "core-api"     = $ApiPidFile
    "agent-worker" = $WorkerPidFile
}

foreach ($name in $services.Keys) {
    $path = $services[$name]
    if (-not (Test-Path $path)) {
        Write-Host "  No pid file for $name"
        continue
    }
    try {
        $content = [System.IO.File]::ReadAllText($path).Trim()
    } catch {
        Write-Host "  Cannot read pid file for $name"
        continue
    }
    $pidVal = $content -replace '\s.*', ''
    if ($pidVal -match '^\d+$') {
        $p = Get-Process -Id $pidVal -ErrorAction SilentlyContinue
        if ($p) {
            & taskkill /F /PID $pidVal 2>$null | Out-Null
            Write-Host "  Stopped $name (pid=$pidVal)"
        } else {
            Write-Host "  $name not running (stale pid $pidVal)"
        }
    } else {
        Write-Host "  Invalid pid file for $name"
    }
    try {
        [System.IO.File]::Delete($path)
    } catch { }
}

Write-Host "Done. If web-console was running in another terminal, stop it with Ctrl+C."
