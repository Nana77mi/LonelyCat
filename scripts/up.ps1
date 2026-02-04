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
    param([string]$Name, [string]$PidFile, [string]$LogPath, [string]$EnvPath, [string[]]$ProcessArgs)
    if (Test-Path $PidFile) {
        $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($oldPid -match '^\d+$' -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
            Write-Host "$Name already running (pid=$oldPid)"
            return
        }
    }
    $env:PYTHONPATH = $EnvPath
    $proc = Start-Process -FilePath $Py -ArgumentList $ProcessArgs -WorkingDirectory $RepoRoot -NoNewWindow `
        -RedirectStandardOutput $LogPath -RedirectStandardError ($LogPath -replace '\.log$', '-err.log') -PassThru
    $proc.Id | Set-Content $PidFile
    Write-Host "Started $Name (pid=$($proc.Id)), log: $LogPath"
}

# Core API
Write-Host "Starting core-api (port $ApiPort)..."
Start-Bg -Name "core-api" -PidFile $ApiPidFile -LogPath "$PidDir\core-api.log" -EnvPath "packages" -ProcessArgs @(
    "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", $ApiPort, "--app-dir", "apps/core-api"
)
Start-Sleep -Seconds 2
$apiPid = Get-Content $ApiPidFile -ErrorAction SilentlyContinue
if ($apiPid -and (Get-Process -Id $apiPid -ErrorAction SilentlyContinue)) {
    Write-Host "  core-api OK: http://localhost:$ApiPort/docs"
} else {
    Write-Host "  core-api may have failed; check .pids\core-api.log"
}

# Agent worker（需能访问 core-api 以在任务完成后发送回复消息）
$env:CORE_API_URL = "http://127.0.0.1:$ApiPort"
Write-Host "Starting agent-worker..."
Start-Bg -Name "agent-worker" -PidFile $WorkerPidFile -LogPath "$PidDir\agent-worker.log" -EnvPath "packages;apps/agent-worker" -ProcessArgs @(
    "-m", "worker.main"
)
Start-Sleep -Seconds 1

$sep = [string]::new([char]61, 42)
Write-Host
Write-Host $sep
Write-Host '  LonelyCat started (API + Worker)'
Write-Host $sep
Write-Host ('  API:       http://localhost:{0}/docs' -f $ApiPort)
Write-Host ('  Web UI:    starting on port {0}' -f $WebPort)
Write-Host '  Stop backend: .\scripts\down.ps1'
Write-Host '  Press Ctrl+C to stop Web UI'
Write-Host $sep
Write-Host

# Web console (foreground)
$env:CORE_API_PORT = $ApiPort
$apps = -join (97,112,112,115 | ForEach-Object { [char]$_ })
$webConsole = -join (119,101,98,45,99,111,110,115,111,108,101 | ForEach-Object { [char]$_ })
$webDir = Join-Path (Join-Path $RepoRoot $apps) $webConsole
Push-Location $webDir
try {
    pnpm dev --host 0.0.0.0 --port $WebPort
} finally {
    Pop-Location
}
