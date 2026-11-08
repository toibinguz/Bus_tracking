# PowerShell Launcher for Hanoi Bus Live ETA Web App Demo
# Requires UTF-8 BOM for Windows PowerShell 5.1 compatibility

# 1. Force UTF-8 Encoding for Console
chcp 65001 >$null
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($true)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($true)
$OutputEncoding = [System.Text.UTF8Encoding]::new($true)

# 2. Ensure current location is project root
$rootDir = $PSScriptRoot
if ($rootDir) {
    Set-Location -Path $rootDir
} else {
    $rootDir = Get-Location
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

# 4. Check if port 8000 is already in use
$targetPort = 8000
$tcpConn = Get-NetTCPConnection -LocalPort $targetPort -State Listen -ErrorAction SilentlyContinue
if ($tcpConn) {
    $ownerPid = $tcpConn.OwningProcess
    Write-Host "[!] Phát hiện tiến trình (PID $ownerPid) đang chiếm cổng $targetPort." -ForegroundColor Yellow
    
    # Check if existing process is already our demo server
    try {
        $check = Invoke-RestMethod -Uri "http://127.0.0.1:$targetPort/api/v1/health" -TimeoutSec 1 -ErrorAction Stop
        if ($check.status -eq "healthy") {
            Write-Host "[+] Máy chủ Demo đã đang chạy sẵn tại http://127.0.0.1:$targetPort!" -ForegroundColor Green
            Write-Host "[*] Đang tự động mở trình duyệt..." -ForegroundColor Cyan
            Start-Process "http://127.0.0.1:$targetPort"
            Write-Host "[!] Bạn có thể mở giao diện tại: http://127.0.0.1:$targetPort" -ForegroundColor Green
            Write-Host "[*] Để khởi động lại từ đầu, hãy đóng cửa sổ terminal cũ hoặc chạy: Stop-Process -Id $ownerPid -Force" -ForegroundColor DarkGray
            exit 0
        }
    } catch {
        # Process is hung or not responding: terminate it
        Write-Host "[*] Đang tự động giải phóng cổng $targetPort..." -ForegroundColor Yellow
        Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 600
    }
}

Write-Host "[*] Đang khởi động máy chủ FastAPI & Uvicorn..." -ForegroundColor Green
Write-Host "[*] Giao diện Người dùng (Web App) : http://127.0.0.1:$targetPort" -ForegroundColor Cyan
Write-Host "[*] Tài liệu tương tác (Swagger UI) : http://127.0.0.1:$targetPort/docs" -ForegroundColor Cyan
Write-Host "[*] Tài liệu ReDoc                 : http://127.0.0.1:$targetPort/redoc" -ForegroundColor Cyan
Write-Host ""
Write-Host "[!] Đang mở trình duyệt sau 2 giây..." -ForegroundColor DarkGray
Write-Host "[!] Nhấn Ctrl+C để dừng máy chủ bất kỳ lúc nào." -ForegroundColor DarkGray
Write-Host "--------------------------------------------------------------------------" -ForegroundColor DarkGray

# Launch browser in background after 2 seconds
Start-Job -ScriptBlock {
    param($port)
    Start-Sleep -Seconds 2
    Start-Process "http://127.0.0.1:$port"
} -ArgumentList $targetPort | Out-Null

# Start Uvicorn
& $pythonExe -m uvicorn module_3_bus_eta_prediction.step_3_5_web_demo.app:app --host 127.0.0.1 --port $targetPort