# PowerShell Launcher & Live Monitor for Hanoi Bus Speed Layer Poller (pure ASCII for Windows PowerShell 5.1)

param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [string]$DbPath,
    [ValidateRange(1, 60)]
    [int]$MonitorIntervalSec = 5
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

if ($DbPath) {
    $env:SERVING_DB_PATH = (Resolve-Path -LiteralPath $DbPath -ErrorAction Stop).Path
} else {
    Remove-Item Env:\SERVING_DB_PATH -ErrorAction SilentlyContinue
}

$pythonExe = Join-Path $rootDir ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "py"
}

Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host " HANOI BUS SPEED LAYER (45s BusMap Baseline + TimBus Gap-Filler)" -ForegroundColor Yellow
Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host ""

$healthUrl = "http://127.0.0.1:$Port/api/health"
$tcpConn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1

if ($tcpConn) {
    $ownerPid = $tcpConn.OwningProcess
    $running = $false
    try {
        $probe = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2 -ErrorAction Stop
        if ($probe.status) {
            $running = $true
        }
    } catch {}

    if ($running) {
        Write-Host "[+] Phat hien Backend + SpeedLayerPoller dang chay (PID $ownerPid, cong $Port)." -ForegroundColor Green
        Write-Host "[*] Chuyen sang che do theo doi Speed Layer truc tiep (moi ${MonitorIntervalSec}s). Nhan Ctrl+C de thoat." -ForegroundColor Cyan
        Write-Host "--------------------------------------------------------------------------" -ForegroundColor DarkGray
        while ($true) {
            $ts = Get-Date -Format "HH:mm:ss"
            try {
                $h = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2 -ErrorAction Stop
                $p = $h.poller
                $counts = $p.counts
                $inc = $p.incidents
                $ageText = if ($null -ne $p.last_cycle_age_sec) { "$($p.last_cycle_age_sec)s ago" } else { "pending" }
                $durText = if ($null -ne $p.last_cycle_duration_sec) { "$($p.last_cycle_duration_sec)s" } else { "-" }
                $incText = if ($inc.error) { "ERR" } else { "$($inc.count)" }
                $line = "[Monitor $ts] app=$($h.status) | poller=$($p.status) | op_hours=$($p.operating_hours) | " +
                        "cycles=$($p.cycle_count) ($ageText, dur=$durText) | " +
                        "busmap=$($counts.busmap_ok)ok/$($counts.busmap_error)err | " +
                        "timbus_rec=$($counts.recovered_live) parked=$($counts.parked_skip) gap=$($counts.on_corridor_gap) err=$($counts.upstream_error) | " +
                        "circuit=$($p.circuit_state) | incidents=$incText"
                if ($p.status -eq "degraded" -or $p.circuit_state -eq "OPEN") {
                    Write-Host $line -ForegroundColor Yellow
                } else {
                    Write-Host $line -ForegroundColor Gray
                }
            } catch {
                Write-Host "[Monitor $ts] Mat ket noi toi $healthUrl (may chu da dung?)" -ForegroundColor Red
            }
            Start-Sleep -Seconds $MonitorIntervalSec
        }
    } else {
        Write-Host "[*] Giai phong cong $Port dang bi treo boi PID $ownerPid..." -ForegroundColor Yellow
        Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
    }
}

Write-Host "[*] Dang khoi dong Backend + SpeedLayerPoller o che do live terminal (khong mo trinh duyet)..." -ForegroundColor Green
Write-Host "[*] API Health Endpoint : $healthUrl" -ForegroundColor Cyan
Write-Host "[*] Trang Debug         : http://127.0.0.1:$Port/debug" -ForegroundColor Cyan
Write-Host "[!] Nhan Ctrl+C de dung Speed Layer & may chu bat ky luc nao." -ForegroundColor DarkGray
Write-Host "--------------------------------------------------------------------------" -ForegroundColor DarkGray

& $pythonExe -m uvicorn modules.eta.web_demo.app:app --host 127.0.0.1 --port $Port --workers 1 --timeout-graceful-shutdown 1
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0 -and $exitCode -ne -1073741510) {
    Write-Host ""
    Write-Host "[!] Tien trinh thoat voi ma loi $exitCode. Nhan phim bat ky de dong..." -ForegroundColor Red
    [void][System.Console]::ReadKey($true)
}
exit 0
