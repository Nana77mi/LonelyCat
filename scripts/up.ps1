# LonelyCat start: core-api (bg), agent-worker (bg), web-console (fg).
# Run from repo root: .\scripts\up.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Venv = Join-Path $RepoRoot ".venv"
$Py = Join-Path $Venv 'Scripts\python.exe'
$PidDir = Join-Path $RepoRoot ".pids"
$ApiPort = 5173
$WebPort = 8000

if (-not (Test-Path $Py)) {
    Write-Host "Run .\scripts\setup.ps1 first."
    exit 1
}
if (-not (Test-Path $PidDir)) {
    New-Item -ItemType Directory -Path $PidDir | Out-Null
}

$ApiPidFile = Join-Path $PidDir "core-api.pid"
$WorkerPidFile = Join-Path $PidDir "agent-worker.pid"

function Start-Bg {
    param([string]$Name, [string]$PidFile, [string]$LogPath, [string]$EnvPath, [string[]]$Args)
    if (Test-Path $PidFile) {
        $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($oldPid -match '^\d+$' -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
            Write-Host "$Name already running (pid=$oldPid)"
            return
        }
    }
    $env:PYTHONPATH = $EnvPath
    $proc = Start-Process -FilePath $Py -ArgumentList $Args -WorkingDirectory $RepoRoot -NoNewWindow `
        -RedirectStandardOutput $LogPath -RedirectStandardError ($LogPath -replace '\.log$', '-err.log') -PassThru
    $proc.Id | Set-Content $PidFile
    Write-Host "Started $Name (pid=$($proc.Id)), log: $LogPath"
}

# Core API
Write-Host "Starting core-api (port $ApiPort)..."
Start-Bg -Name "core-api" -PidFile $ApiPidFile -LogPath "$PidDir\core-api.log" -EnvPath "packages" -Args @(
    "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", $ApiPort, "--app-dir", "apps/core-api"
)
Start-Sleep -Seconds 2
$apiPid = Get-Content $ApiPidFile -ErrorAction SilentlyContinue
if ($apiPid -and (Get-Process -Id $apiPid -ErrorAction SilentlyContinue)) {
    Write-Host "  core-api OK: http://localhost:$ApiPort/docs"
} else {
    Write-Host "  core-api may have failed; check .pids\core-api.log"
}

# Agent worker
Write-Host "Starting agent-worker..."
Start-Bg -Name "agent-worker" -PidFile $WorkerPidFile -LogPath "$PidDir\agent-worker.log" -EnvPath "packages;apps/agent-worker" -Args @(
    "-m", "worker.main"
)
Start-Sleep -Seconds 1

Write-Host ''
Write-Host '=========================================='
Write-Host '  LonelyCat 服务已启动（API + Worker）'
Write-Host '=========================================='
Write-Host "  API:       http://localhost:$ApiPort/docs"
Write-Host "  用户界面:  即将启动 (端口 $WebPort)"
Write-Host '  停止后端:  .\scripts\down.ps1'
Write-Host '  按 Ctrl+C 停止 Web 界面'
Write-Host '=========================================='
Write-Host ''

# Web console (foreground)
$env:CORE_API_PORT = $ApiPort
$webDir = Join-Path $RepoRoot 'apps\web-console'
Push-Location $webDir
try {
    pnpm dev --host 0.0.0.0 --port $WebPort
} finally {
    Pop-Location
}
