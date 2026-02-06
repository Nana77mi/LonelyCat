# Build LonelyCat sandbox image (lonelycat-sandbox:py312). See docs/spec/sandbox.md.
# Run from repo root: .\scripts\build_sandbox_image.ps1
# Requires Docker Desktop (Windows) or Docker in WSL2.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Dockerfile = Join-Path $RepoRoot "docker\sandbox\Dockerfile"
if (-not (Test-Path $Dockerfile)) {
    Write-Error "Dockerfile not found at $Dockerfile. Run from repo root."
}
Set-Location $RepoRoot

# Intel/AMD: clean rebuild to force amd64 base (set LONELYCAT_SANDBOX_REBUILD_BASE=1)
if ($env:LONELYCAT_SANDBOX_REBUILD_BASE -eq "1") {
    Write-Host "Clean rebuild: remove images and build cache, pull linux/amd64 base ..." -ForegroundColor Yellow
    $prevErr = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    docker rmi lonelycat-sandbox:py312 2>&1 | Out-Null
    docker rmi python:3.12-slim 2>&1 | Out-Null
    $ErrorActionPreference = $prevErr
    docker builder prune -f | Out-Null
    docker pull --platform linux/amd64 python:3.12-slim
    if ($LASTEXITCODE -ne 0) {
        throw "docker pull python:3.12-slim failed."
    }
}

Write-Host "Building lonelycat-sandbox:py312 from docker/sandbox/Dockerfile (--platform linux/amd64 --pull --no-cache) ..." -ForegroundColor Cyan
docker build --platform linux/amd64 --pull --no-cache -f docker/sandbox/Dockerfile -t lonelycat-sandbox:py312 .
if ($LASTEXITCODE -ne 0) {
    throw "docker build failed."
}
Write-Host "Done. Verify with: docker run --platform linux/amd64 --rm lonelycat-sandbox:py312 python -c ""print(1)""" -ForegroundColor Green
# 若仍失败，可自检架构: docker image inspect lonelycat-sandbox:py312 --format ""{{.Architecture}}"" 应为 amd64
# PowerShell 难以传空 --entrypoint，改用: --entrypoint python，命令为 -c ""print(1)""
Write-Host "Alt verify: docker run --platform linux/amd64 --rm --entrypoint python lonelycat-sandbox:py312 -c ""print(1)""" -ForegroundColor DarkGray
