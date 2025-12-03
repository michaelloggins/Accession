Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

Set-Location -Path "C:\Projects\DocIntelligence"

# Restart server with fresh database
Write-Host "=== Restarting with Fresh Database ===" -ForegroundColor Cyan

# Activate virtual environment
Write-Host "`nActivating virtual environment..." -ForegroundColor Yellow
& .\venv\Scripts\Activate.ps1
Write-Host "  Virtual environment activated" -ForegroundColor Green

# Stop any running uvicorn processes
Write-Host "`nStopping uvicorn server..." -ForegroundColor Yellow
Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like "*uvicorn*"} | Stop-Process -Force
Start-Sleep -Seconds 2

# Delete test database
Write-Host "Deleting test.db..." -ForegroundColor Yellow
if (Test-Path "test.db") {
    Remove-Item "test.db" -Force
    Write-Host "  Database deleted" -ForegroundColor Green
} else {
    Write-Host "  No database to delete" -ForegroundColor Gray
}

# Recreate test user
Write-Host "`nCreating test user..." -ForegroundColor Yellow
python test_login.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Failed to create test user" -ForegroundColor Red
    exit 1
}

# Start server
Write-Host "`nStarting server..." -ForegroundColor Yellow
Write-Host "Server will start at http://localhost:8000" -ForegroundColor Cyan
Write-Host "Login with: admin@test.com / any password`n" -ForegroundColor Cyan

python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
