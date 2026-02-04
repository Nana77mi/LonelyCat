# Diagnose "No Python at '/usr/bin\python.exe'" on Windows.
# Run from repo root: .\scripts\diagnose-python.ps1

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $RepoRoot ".venv\Scripts\python.exe"

Write-Host "1. Checking venv python exists..."
if (-not (Test-Path $Py)) {
    Write-Host "   FAIL: $Py not found. Run .\scripts\setup.ps1 first."
    exit 1
}
Write-Host "   OK: $Py"

$PyvenvCfg = Join-Path $RepoRoot ".venv\pyvenv.cfg"
if (Test-Path $PyvenvCfg) {
    Write-Host "1b. pyvenv.cfg (if 'home' has /usr, venv was created under WSL/Git Bash):"
    Get-Content $PyvenvCfg | ForEach-Object { Write-Host "   $_" }
} else {
    Write-Host "1b. pyvenv.cfg not found."
}

Write-Host "2. Python executable (sys.executable)..."
& $Py -c "import sys; print('   ', sys.executable)"

Write-Host "3. Env vars that might affect Python path..."
foreach ($n in @("PYTHONHOME", "PYTHONEXECUTABLE", "VIRTUAL_ENV", "CONDA_PREFIX")) {
    $v = [Environment]::GetEnvironmentVariable($n, "Process")
    if (-not $v) { $v = [Environment]::GetEnvironmentVariable($n, "User") }
    if (-not $v) { $v = [Environment]::GetEnvironmentVariable($n, "Machine") }
    if ($v) { Write-Host "   $n = $v" } else { Write-Host "   $n = (not set)" }
}

Write-Host "4. Which import prints 'No Python at' (run step by step)..."
& $Py -c @"
import sys
print('   import sys -> ok')
# Minimal import chain
print('   about to import worker...')
import worker
print('   import worker -> ok')
print('   about to import agent_worker...')
import agent_worker
print('   import agent_worker -> ok')
print('   All imports OK.')
"@

Write-Host "5. If step 4 showed 'No Python at' above a line, that import triggered it."
Write-Host "   If you see 'All imports OK' at the end, imports succeeded (message is harmless)."
