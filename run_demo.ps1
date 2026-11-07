# PowerShell Launcher for Hanoi Bus Live ETA Web App Demo
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host " HANOI BUS BIG DATA & REAL-TIME ETA PREDICTION - WEB APP DEMO" -ForegroundColor Yellow
Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[*] Khởi động máy chủ FastAPI & Uvicorn..." -ForegroundColor Green
Write-Host "[*] Giao diện Người dùng (Web App) : http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "[*] Tài liệu tương tác (Swagger UI) : http://127.0.0.1:8000/docs" -ForegroundColor Cyan
Write-Host "[*] Tài liệu ReDoc                 : http://127.0.0.1:8000/redoc" -ForegroundColor Cyan
Write-Host ""
Write-Host "[!] Nhấn Ctrl+C để dừng máy chủ bất kỳ lúc nào." -ForegroundColor DarkGray
Write-Host "--------------------------------------------------------------------------" -ForegroundColor DarkGray

& ".\.venv\Scripts\python.exe" -m uvicorn module_3_bus_eta_prediction.step_3_5_web_demo.app:app --host 127.0.0.1 --port 8000 --reload
