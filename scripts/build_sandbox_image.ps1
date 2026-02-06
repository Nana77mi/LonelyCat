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

Write-Host "Building lonelycat-sandbox:py312 from docker/sandbox/Dockerfile ..." -ForegroundColor Cyan
docker build -f docker/sandbox/Dockerfile -t lonelycat-sandbox:py312 .
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker build failed."
}
Write-Host "Done. Verify with: docker run --rm lonelycat-sandbox:py312 python -c ""print(1)""" -ForegroundColor Green
