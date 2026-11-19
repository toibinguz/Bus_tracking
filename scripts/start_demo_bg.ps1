param(
    [int]$Port = 8000,
    [string]$BindHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeDir = Join-Path $RepoRoot "runtime"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

$PidFile = Join-Path $RuntimeDir "demo_server.pid"
$OutLog = Join-Path $RuntimeDir "demo_server.log"
$ErrLog = Join-Path $RuntimeDir "demo_server.err.log"

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    Write-Host "[!] Port $Port dang duoc su dung boi PID $($existing.OwningProcess)." -ForegroundColor Yellow
    Write-Host "    Neu la server cu, chay scripts\stop_demo_bg.ps1 hoac dung -Port khac."
    exit 1
}

$argsList = @(
    "-m", "uvicorn",
    "module_3_bus_eta_prediction.step_3_5_web_demo.app:app",
    "--host", $BindHost,
    "--port", "$Port",
    "--workers", "1"
)

$proc = Start-Process -FilePath "python" `
    -ArgumentList $argsList `
    -WorkingDirectory $RepoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -PassThru

$proc.Id | Set-Content -Path $PidFile -Encoding ASCII

$healthUrl = "http://${BindHost}:${Port}/api/health"
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $resp = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        if ($resp.status) {
            $ready = $true
            break
        }
    } catch {}
}

if ($ready) {
    Write-Host "[OK] Server + SpeedLayerPoller da chay ngam (PID $($proc.Id))." -ForegroundColor Green
    Write-Host "     Hanh khach : http://${BindHost}:${Port}/"
    Write-Host "     Debug      : http://${BindHost}:${Port}/debug"
    Write-Host "     De dung sau demo: scripts\stop_demo_bg.bat"
} else {
    Write-Host "[!] Server da khoi dong (PID $($proc.Id)) nhung chua phan hoi /api/health. Xem log: $ErrLog" -ForegroundColor Yellow
}
