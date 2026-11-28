# PowerShell Launcher for Hanoi Bus Live ETA Web App Demo (pure ASCII for Windows PowerShell 5.1)

param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [switch]$NoBrowser,
    [string]$DbPath
)

# 1. Force UTF-8 Encoding for Console & Python subprocess without emitting BOM
chcp 65001 >$null
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8NoBom
[Console]::InputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# 2. Ensure current location is project root
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

# 3. Locate Python executable in .venv
$pythonExe = Join-Path $rootDir ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "py"
}

Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host " HANOI BUS BIG DATA & REAL-TIME ETA PREDICTION - WEB APP DEMO" -ForegroundColor Yellow
Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host ""

# 4. Check if port is already in use
$targetPort = $Port
$tcpConn = Get-NetTCPConnection -LocalPort $targetPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($tcpConn) {
    $ownerPid = $tcpConn.OwningProcess
    Write-Host "[!] Phat hien tien trinh (PID $ownerPid) dang chiem cong $targetPort." -ForegroundColor Yellow

    # Check if existing process is already our demo server
    try {
        $check = Invoke-RestMethod -Uri "http://127.0.0.1:$targetPort/api/health" -TimeoutSec 2 -ErrorAction Stop
        if ($check.status) {
            Write-Host "[+] May chu Demo da dang chay san tai http://127.0.0.1:$targetPort (status=$($check.status))!" -ForegroundColor Green
            if (-not $NoBrowser) {
                Write-Host "[*] Dang tu dong mo trinh duyet..." -ForegroundColor Cyan
                Start-Process "http://127.0.0.1:$targetPort"
            }
            Write-Host "[!] Mo giao dien tai: http://127.0.0.1:$targetPort" -ForegroundColor Green
            Write-Host "[*] De khoi dong lai tu dau, dong cua so cu hoac chay: Stop-Process -Id $ownerPid -Force" -ForegroundColor DarkGray
            exit 0
        }
    } catch {
        # Process is hung or not our server: terminate it
        Write-Host "[*] Dang tu dong giai phong cong $targetPort..." -ForegroundColor Yellow
        Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
    }
}

Write-Host "[*] Dang khoi dong may chu FastAPI & Uvicorn..." -ForegroundColor Green
Write-Host "[*] Giao dien Nguoi dung (Web App) : http://127.0.0.1:$targetPort" -ForegroundColor Cyan
Write-Host "[*] Giao dien Giam sat (Debug)     : http://127.0.0.1:$targetPort/debug" -ForegroundColor Cyan
Write-Host "[*] Tai lieu API (Swagger UI)     : http://127.0.0.1:$targetPort/docs" -ForegroundColor Cyan
Write-Host ""
if (-not $NoBrowser) {
    Write-Host "[*] Trinh duyet se tu mo ngay khi may chu san sang..." -ForegroundColor DarkGray
}
Write-Host "[!] Nhan Ctrl+C de dung may chu bat ky luc nao." -ForegroundColor DarkGray
Write-Host "--------------------------------------------------------------------------" -ForegroundColor DarkGray

# Launch lightweight in-process Runspace (zero PowerShell child process overhead) to open browser on readiness
$browserPs = $null
$browserHandle = $null
if (-not $NoBrowser) {
    $browserPs = [powershell]::Create()
    [void]$browserPs.AddScript({
        param([int]$Port)
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        $url = "http://127.0.0.1:$Port"
        $healthUrl = "$url/api/health"
        while ([DateTime]::UtcNow -lt $deadline) {
            try {
                $resp = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1 -ErrorAction Stop
                if ($resp.status) {
                    Start-Process $url
                    return
                }
            } catch {
                Start-Sleep -Milliseconds 200
            }
        }
    }).AddArgument($targetPort)
    $browserHandle = $browserPs.BeginInvoke()
}

try {
    & $pythonExe -m uvicorn modules.eta.web_demo.app:app --host 127.0.0.1 --port $targetPort --timeout-graceful-shutdown 1
    $exitCode = $LASTEXITCODE
} finally {
    if ($browserPs) {
        try {
            if ($browserHandle -and -not $browserHandle.IsCompleted) {
                $browserPs.Stop()
            }
        } catch {}
        $browserPs.Dispose()
    }
}

# Pause only on genuine non-Ctrl+C errors (-1073741510 == 0xC000013A STATUS_CONTROL_C_EXIT)
if ($exitCode -ne 0 -and $exitCode -ne -1073741510) {
    Write-Host ""
    Write-Host "[!] May chu thoat voi ma loi $exitCode. Nhan phim bat ky de dong..." -ForegroundColor Red
    [void][System.Console]::ReadKey($true)
}
exit 0
