$ErrorActionPreference = "SilentlyContinue"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PidFile = Join-Path $RepoRoot "data\staging\demo_server\demo_server.pid"

if (-not (Test-Path $PidFile)) {
    Write-Host "[!] Khong tim thay file PID ($PidFile)." -ForegroundColor Yellow
    exit 0
}

$pidText = (Get-Content $PidFile -Raw).Trim()
if ($pidText -match '^\d+$') {
    $procId = [int]$pidText
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $procId -Force
        Write-Host "[OK] Da dung server demo (PID $procId)." -ForegroundColor Green
    } else {
        Write-Host "[i] Tien trinh PID $procId khong con chay."
    }
}
Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
