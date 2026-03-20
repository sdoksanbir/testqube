param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$venvDir = Join-Path $backendDir ".venv"
$activateScript = Join-Path $venvDir "Scripts\Activate.ps1"

if (-not (Test-Path $backendDir)) { throw "backend klasoru bulunamadi: $backendDir" }
if (-not (Test-Path $frontendDir)) { throw "frontend klasoru bulunamadi: $frontendDir" }

# Migration helper:
# Desktop app had one executable entry. This script restores a single-entry workflow for web MVP.
if (-not (Test-Path $activateScript)) {
    Write-Host "Python virtualenv olusturuluyor..." -ForegroundColor Yellow
    Push-Location $backendDir
    python -m venv .venv
    Pop-Location
}

Write-Host "Backend bagimliliklari kontrol/kurulum..." -ForegroundColor Yellow
Push-Location $backendDir
& $activateScript
pip install -r requirements.txt
Pop-Location

Write-Host "Frontend bagimliliklari kontrol/kurulum..." -ForegroundColor Yellow
Push-Location $frontendDir
npm install
Pop-Location

$backendCmd = "cd `"$backendDir`"; . `"$activateScript`"; uvicorn app.main:app --reload --port $BackendPort"
$frontendCmd = "cd `"$frontendDir`"; npm run dev -- --port $FrontendPort"

Write-Host "Backend yeni terminalde baslatiliyor..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $backendCmd | Out-Null

Write-Host "Frontend mevcut terminalde baslatiliyor..." -ForegroundColor Green
Write-Host "UI: http://localhost:$FrontendPort | API: http://localhost:$BackendPort/health" -ForegroundColor Cyan
Push-Location $frontendDir
npm run dev -- --port $FrontendPort
Pop-Location
