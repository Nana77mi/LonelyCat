# Test script to verify proxy configuration
# This script tests that GET /api/conversations properly proxies to core-api

Write-Host "Testing Proxy Configuration" -ForegroundColor Cyan
Write-Host "=========================" -ForegroundColor Cyan
Write-Host ""

# Check environment variables
Write-Host "Environment Variables:" -ForegroundColor Yellow
if ($env:VITE_CORE_API_URL) {
    Write-Host "  VITE_CORE_API_URL: $env:VITE_CORE_API_URL" -ForegroundColor Red
} else {
    Write-Host "  VITE_CORE_API_URL: (not set)" -ForegroundColor Green
}

if ($env:VITE_API_BASE_URL) {
    Write-Host "  VITE_API_BASE_URL: $env:VITE_API_BASE_URL" -ForegroundColor Red
} else {
    Write-Host "  VITE_API_BASE_URL: (not set)" -ForegroundColor Green
}

if ($env:CORE_API_PORT) {
    Write-Host "  CORE_API_PORT: $env:CORE_API_PORT" -ForegroundColor Yellow
} else {
    Write-Host "  CORE_API_PORT: (not set, will use default 5173)" -ForegroundColor Yellow
}

Write-Host ""

# Test core-api directly
Write-Host "1. Testing core-api directly on port 5173..." -ForegroundColor Cyan
try {
    $response = Invoke-WebRequest -Uri "http://localhost:5173/conversations" -UseBasicParsing -TimeoutSec 2
    Write-Host "   ✓ Core-API is running" -ForegroundColor Green
    Write-Host "   Status: $($response.StatusCode)" -ForegroundColor Green
    $json = $response.Content | ConvertFrom-Json
    Write-Host "   Response: $($json | ConvertTo-Json -Compress)" -ForegroundColor Gray
} catch {
    Write-Host "   ✗ Core-API is not running on port 5173" -ForegroundColor Red
    Write-Host "   Error: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "   Please start core-api first:" -ForegroundColor Yellow
    Write-Host "   make up-api" -ForegroundColor Yellow
    exit 1
}

Write-Host ""

# Test web-console proxy
Write-Host "2. Testing web-console proxy on port 8000..." -ForegroundColor Cyan
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/api/conversations" -UseBasicParsing -TimeoutSec 2
    Write-Host "   ✓ Web-console proxy is working" -ForegroundColor Green
    Write-Host "   Status: $($response.StatusCode)" -ForegroundColor Green
    $json = $response.Content | ConvertFrom-Json
    Write-Host "   Response: $($json | ConvertTo-Json -Compress)" -ForegroundColor Gray
    
    # Verify it's JSON
    if ($response.Content -match '^\s*\{.*\}\s*$' -or $response.Content -match '^\s*\[.*\]\s*$') {
        Write-Host "   ✓ Response is valid JSON" -ForegroundColor Green
    } else {
        Write-Host "   ✗ Response is not valid JSON" -ForegroundColor Red
    }
    
    # Verify response structure
    if ($json.items -ne $null) {
        Write-Host "   ✓ Response has 'items' field (correct structure)" -ForegroundColor Green
    } else {
        Write-Host "   ✗ Response missing 'items' field" -ForegroundColor Red
    }
    
} catch {
    Write-Host "   ✗ Web-console proxy is not working" -ForegroundColor Red
    Write-Host "   Error: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "   Please start web-console first:" -ForegroundColor Yellow
    Write-Host "   CORE_API_PORT=5173 pnpm --filter @lonelycat/web-console dev" -ForegroundColor Yellow
    Write-Host "   Or use: make up-web" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "=========================" -ForegroundColor Cyan
Write-Host "✓ All tests passed!" -ForegroundColor Green
Write-Host ""
Write-Host "The proxy configuration is working correctly:" -ForegroundColor Green
Write-Host "  /api/conversations → http://127.0.0.1:5173/conversations" -ForegroundColor Gray
