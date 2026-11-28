# PowerShell Launcher for Standalone Speed Layer Worker (pure ASCII for Windows PowerShell 5.1)

param(
    [string]$DbPath,
    [string]$ViewDbPath,
    [ValidateRange(5, 3600)]
    [int]$IntervalSec = 45
)

chcp 65001 >$null
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8NoBom
[Console]::InputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$rootDir = $PSScriptRoot
if ($rootDir) {
    Set-Location -Path $rootDir
} else {
    $rootDir = Get-Location
}

$workerArgs = @("scripts\run_speed_layer.py", "--interval", "$IntervalSec")
if ($DbPath) {
    $resolvedDb = (Resolve-Path -LiteralPath $DbPath -ErrorAction Stop).Path
    $env:SERVING_DB_PATH = $resolvedDb
    $workerArgs += @("--db-path", $resolvedDb)
} else {
    Remove-Item Env:\SERVING_DB_PATH -ErrorAction SilentlyContinue
}
if ($ViewDbPath) {
    $resolvedView = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ViewDbPath)
    $env:SPEED_VIEW_DB_PATH = $resolvedView
    $workerArgs += @("--view-db", $resolvedView)
} else {
    Remove-Item Env:\SPEED_VIEW_DB_PATH -ErrorAction SilentlyContinue
}

$pythonExe = Join-Path $rootDir ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "py"
}

Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host " HANOI BUS SPEED LAYER WORKER (Standalone 45s BusMap + TimBus Gap-Filler)" -ForegroundColor Yellow
Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host "[*] Che do doc lap: KHONG khoi dong Serving Layer / FastAPI / Uvicorn." -ForegroundColor Green
Write-Host "[*] Nhan Ctrl+C 1 lan de dung Speed Layer Worker sach se." -ForegroundColor DarkGray
Write-Host "--------------------------------------------------------------------------" -ForegroundColor DarkGray

& $pythonExe @workerArgs
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0 -and $exitCode -ne -1073741510) {
    Write-Host ""
    Write-Host "[!] Speed Layer thoat voi ma loi $exitCode. Nhan phim bat ky de dong..." -ForegroundColor Red
    [void][System.Console]::ReadKey($true)
}
exit 0
